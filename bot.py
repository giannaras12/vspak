import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
from flask import Flask
import asyncio
import random
import json
from datetime import datetime
import os

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.dm_messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Constants
LOG_CHANNEL_ID = 1386555864831365197
DUTY_CHANNEL_ID = 1386555864831365198
ADMIN_USER_ID = 848805899790581780 

# Load or initialize points
try:
    with open("points.json", "r") as f:
        points = json.load(f)
except FileNotFoundError:
    points = {}

active_duties = {}
reminder_tasks = {}

class ReminderLoop:
    def __init__(self, user):
        self.user = user
        self.cancelled = False

    async def start(self):
        while not self.cancelled:
            wait_time = random.randint(1200, 1800)  # 20 to 30 minutes in seconds
            await asyncio.sleep(wait_time)

            if self.cancelled:
                break

            view = ReminderView(self.user)
            embed = discord.Embed(title="Duty Reminder",
                                  description="You're currently on duty. Do you want to continue or end?",
                                  color=discord.Color.orange())
            embed.set_footer(text="You have 2 minutes to respond.")

            try:
                await self.user.send(embed=embed, view=view)
                await log_event("Reminder Sent", self.user, datetime.now())
                await view.wait()

                if not view.responded:
                    await end_duty(self.user, auto=True)
            except discord.Forbidden:
                await log_event("Failed to send DM reminder", self.user, datetime.now())
                await end_duty(self.user, auto=True)

class ReminderView(View):
    def __init__(self, user):
        super().__init__(timeout=120)
        self.user = user
        self.responded = False

    async def on_timeout(self):
        self.stop()

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.green)
    async def continue_callback(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This reminder isn't for you.", ephemeral=True)
            return

        self.responded = True
        await interaction.response.send_message("Duty continued.", ephemeral=True)
        await log_event("User Continued", self.user, datetime.now())

        # Restart reminder task
        if self.user.id in reminder_tasks:
            reminder_tasks[self.user.id].cancel()

        reminder_tasks[self.user.id] = asyncio.create_task(ReminderLoop(self.user).start())
        self.stop()

    @discord.ui.button(label="End", style=discord.ButtonStyle.red)
    async def end_callback(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This reminder isn't for you.", ephemeral=True)
            return

        self.responded = True
        await interaction.response.send_message("Duty ended.", ephemeral=True)
        await end_duty(self.user)
        self.stop()

class DutyView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(StartDuty())
        self.add_item(EndDuty())

class StartDuty(Button):
    def __init__(self):
        super().__init__(label="Start Duty", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        if user.id in active_duties:
            await interaction.response.send_message("You're already on duty!", ephemeral=True)
            return

        active_duties[user.id] = {
            "start_time": datetime.now(),
            "points": 0,
            "continues": 0
        }

        reminder_tasks[user.id] = asyncio.create_task(ReminderLoop(user).start())

        embed = discord.Embed(title="Duty Started", color=discord.Color.blue())
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Time", value=datetime.now().strftime("%A, %d %B %Y %H:%M %p"), inline=False)
        embed.add_field(name="Start Time", value=datetime.now().strftime("%A, %d %B %Y %H:%M %p"), inline=False)
        await interaction.response.send_message("Duty started!", ephemeral=True)
        await log_channel.send(embed=embed)

class EndDuty(Button):
    def __init__(self):
        super().__init__(label="End Duty", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        if user.id not in active_duties:
            await interaction.response.send_message("You're not on duty.", ephemeral=True)
            return

        await end_duty(user)
        await interaction.response.send_message("Duty ended.", ephemeral=True)

async def end_duty(user, auto=False):
    duty = active_duties.pop(user.id, None)
    if not duty:
        return

    if user.id in reminder_tasks:
        reminder_tasks[user.id].cancel()

    end_time = datetime.now()
    start_time = duty["start_time"]
    duration = end_time - start_time

    earned_points = int(duration.total_seconds() // 240)  # 1 point per 4 minutes
    total_points = points.get(str(user.id), 0) + earned_points
    points[str(user.id)] = total_points

    with open("points.json", "w") as f:
        json.dump(points, f)

    embed = discord.Embed(title=f"Duty {'Auto-' if auto else ''}Ended", color=discord.Color.red())
    embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
    embed.add_field(name="End Time", value=end_time.strftime("%A, %d %B %Y %H:%M %p"), inline=False)
    embed.add_field(name="Duration", value=str(duration), inline=False)
    embed.add_field(name="Points Earned", value=str(earned_points), inline=False)
    embed.add_field(name="Continues", value=str(duty.get("continues", 0)), inline=False)
    await log_channel.send(embed=embed)

async def log_event(title, user, time):
    embed = discord.Embed(title=title, color=discord.Color.teal())
    embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
    embed.add_field(name="Time", value=time.strftime("%A, %d %B %Y %H:%M %p"), inline=False)
    await log_channel.send(embed=embed)

@bot.event
async def on_ready():
    global log_channel
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    duty_channel = bot.get_channel(DUTY_CHANNEL_ID)
    await duty_channel.send(embed=discord.Embed(title="Duty Handler", description="Use the buttons below to manage your duty.", color=discord.Color.gold()), view=DutyView())
    print(f"Logged in as {bot.user}")

@bot.tree.command()
@app_commands.checks.has_permissions(administrator=True)
async def total(interaction: discord.Interaction, user_id: str):
    user_points = points.get(user_id, 0)
    await interaction.response.send_message(f"User <@{user_id}> has {user_points} points.", ephemeral=True)

@bot.tree.command()
@app_commands.checks.has_permissions(administrator=True)
async def resetpoints(interaction: discord.Interaction, user_id: str):
    points[user_id] = 0
    with open("points.json", "w") as f:
        json.dump(points, f)
    await interaction.response.send_message(f"Points reset for <@{user_id}>.", ephemeral=True)

@bot.tree.command()
@app_commands.checks.has_permissions(administrator=True)
async def addpoints(interaction: discord.Interaction, user_id: str, amount: int):
    points[user_id] = points.get(user_id, 0) + amount
    with open("points.json", "w") as f:
        json.dump(points, f)
    await interaction.response.send_message(f"Added {amount} points to <@{user_id}>.", ephemeral=True)

@bot.tree.command()
async def forceend(interaction: discord.Interaction, user_id: str):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return
    user = bot.get_user(int(user_id))
    if user_id not in active_duties:
        await interaction.response.send_message("That user is not on duty.", ephemeral=True)
        return
    await end_duty(user, auto=True)
    await interaction.response.send_message(f"Force ended duty for <@{user_id}>.", ephemeral=True)

@bot.tree.command()
async def viewduties(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    if not active_duties:
        await interaction.response.send_message("No active duties.", ephemeral=True)
        return

    embed = discord.Embed(title="Active Duties", color=discord.Color.green())
    for uid in active_duties:
        user = bot.get_user(uid)
        embed.add_field(name=user.name, value=f"{user} ({uid})", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Flask server for uptime ping
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

import threading
threading.Thread(target=run).start()

# Run bot
bot.run(os.getenv("BOT_TOKEN"))
