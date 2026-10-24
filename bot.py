import os
import sys
import subprocess
import importlib
import asyncio
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import signal
import logging

# ตั้งค่า logging
logging.basicConfig(level=logging.INFO)

# ==================== AUTO INSTALL ====================
def install_package(package):
    """ติดตั้ง package แบบไม่มี error"""
    try:
        importlib.import_module(package.replace('-', '_'))
        print(f'✅ {package} already installed')
        return True
    except ImportError:
        print(f'📦 Installing {package}...')
        try:
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', package, '--quiet', '--no-cache-dir'],
                check=True,
                capture_output=True,
                text=True
            )
            print(f'✅ {package} installed')
            return True
        except subprocess.CalledProcessError as e:
            print(f'❌ Failed: {e.stderr}')
            return False

# Install packages
packages = ['discord.py']
for pkg in packages:
    install_package(pkg)

# ==================== BOT ====================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# จัดการ Signal
def signal_handler(sig, frame):
    print('\n🛑 Received interrupt signal, shutting down...')
    asyncio.create_task(bot.close())
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class DarkCorePanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.target = None
        self.target_user = None
        self.spam_message = 'ใส่ข้อความที่จะยิง'
        self.spam_count = 10
        self.spam_delay = 0.5
        self.is_spamming = False
        
    @discord.ui.button(label='🎯 ตั้งเป้า', style=discord.ButtonStyle.primary, row=0)
    async def set_target(self, interaction: discord.Interaction, button: Button):
        modal = Modal(title='🎯 ตั้งค่าเป้าหมาย')
        modal.add_item(TextInput(
            label='ชื่อหรือ ID เป้าหมาย',
            placeholder='ใส่ชื่อหรือ ID (ไม่ต้องมี @)',
            required=True,
            style=discord.TextStyle.short
        ))
        
        async def on_submit(interaction: discord.Interaction):
            target = interaction.data['components'][0]['components'][0]['value']
            self.target = target
            
            # พยายามหา user ในเซิร์ฟเวอร์
            self.target_user = None
            guild = interaction.guild
            if guild:
                for member in guild.members:
                    if member.name == target or member.display_name == target or str(member.id) == target:
                        self.target_user = member
                        break
            
            await interaction.response.send_message(
                f'✅ ตั้งเป้าหมาย: **{target}**',
                ephemeral=True
            )
        
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label='🔫 ยิงDm', style=discord.ButtonStyle.success, row=0)
    async def spam_target(self, interaction: discord.Interaction, button: Button):
        """สแปมข้อความไปยังเป้าหมาย"""
        if self.is_spamming:
            await interaction.response.send_message('⏳ กำลังยิงอยู่...', ephemeral=True)
            return
            
        if not self.target:
            await interaction.response.send_message('❌ ตั้งเป้าหมายก่อน!', ephemeral=True)
            return
        
        # สร้าง Modal สำหรับตั้งค่าสแปม
        modal = Modal(title='⚒️ ตั้งค่าสแปม')
        modal.add_item(TextInput(
            label='ข้อความ',
            placeholder='ข้อความที่จะส่ง',
            default=self.spam_message,
            required=True,
            style=discord.TextStyle.paragraph
        ))
        modal.add_item(TextInput(
            label='จำนวน',
            placeholder='1-400',
            default=str(self.spam_count),
            required=True,
            style=discord.TextStyle.short
        ))
        modal.add_item(TextInput(
            label='ระยะห่าง (วินาที)',
            placeholder='0.5-2.0',
            default=str(self.spam_delay),
            required=True,
            style=discord.TextStyle.short
        ))
        
        async def on_submit(interaction: discord.Interaction):
            try:
                message = interaction.data['components'][0]['components'][0]['value']
                count = int(interaction.data['components'][1]['components'][0]['value'])
                delay = float(interaction.data['components'][2]['components'][0]['value'])
                
                count = max(1, min(400, count))
                delay = max(0.5, min(2.0, delay))
                
                self.spam_message = message
                self.spam_count = count
                self.spam_delay = delay
                self.is_spamming = True
                
                await interaction.response.send_message(
                    f'🔄 กำลังยิงไปที่ **{self.target}**\n'
                    f'📊 {count} ครั้ง | ⏱️ {delay} วินาที',
                    ephemeral=False
                )
                
                # ค้นหา user จากชื่อ/ID ทุกที่ (ทั้งในและนอกเซิร์ฟเวอร์)
                target_user = None
                target_id = None
                
                # ตรวจสอบว่าเป็น ID หรือชื่อ
                if self.target.isdigit():
                    target_id = int(self.target)
                    try:
                        # พยายามดึง user จาก ID (แม้จะอยู่นอกเซิร์ฟเวอร์)
                        target_user = await bot.fetch_user(target_id)
                    except:
                        target_user = None
                else:
                    # ถ้าเป็นชื่อ ให้หาในเซิร์ฟเวอร์ก่อน
                    guild = interaction.guild
                    if guild:
                        for member in guild.members:
                            if member.name == self.target or member.display_name == self.target:
                                target_user = member
                                break
                    
                    # ถ้าไม่พบในเซิร์ฟเวอร์ ให้ลองค้นหาจาก ID (ถ้าเป็น ID)
                    if not target_user:
                        try:
                            target_user = await bot.fetch_user(int(self.target))
                        except:
                            pass
                
                if not target_user:
                    await interaction.followup.send(
                        f'❌ ไม่พบผู้ใช้: **{self.target}**',
                        ephemeral=True
                    )
                    self.is_spamming = False
                    return
                
                # เริ่มสแปม
                sent_count = 0
                try:
                    for i in range(count):
                        try:
                            await target_user.send(message)
                            sent_count += 1
                            await asyncio.sleep(delay)
                        except discord.Forbidden:
                            await interaction.followup.send(
                                f'❌ ไม่สามารถส่ง DM ไปยัง **{target_user.name}** (ปิด DM)',
                                ephemeral=False
                            )
                            break
                        except discord.HTTPException as e:
                            if e.status == 429:
                                retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
                                await asyncio.sleep(retry_after)
                                continue
                            else:
                                await interaction.followup.send(
                                    f'⚠️ Error: {str(e)[:100]}',
                                    ephemeral=True
                                )
                                break
                        except Exception as e:
                            await interaction.followup.send(
                                f'⚠️ Error: {str(e)[:100]}',
                                ephemeral=True
                            )
                            break
                    
                    if sent_count > 0:
                        await interaction.followup.send(
                            f'✅ ยิงสแปมเสร็จ!\n'
                            f'👤 {target_user.name}\n'
                            f'📊 {sent_count}/{count} ครั้ง',
                            ephemeral=False
                        )
                except Exception as e:
                    await interaction.followup.send(
                        f'❌ Error: {str(e)[:100]}',
                        ephemeral=True
                    )
                finally:
                    self.is_spamming = False
                    
            except ValueError:
                await interaction.response.send_message(
                    '❌ ใส่ตัวเลขให้ถูกต้อง!',
                    ephemeral=True
                )
                self.is_spamming = False
        
        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label='📊 สถานะ', style=discord.ButtonStyle.gray, row=0)
    async def check_status(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title='📊 DARKCORE STATUS',
            description=f'🎯 **เป้า:** {self.target or "ยังไม่ตั้ง"}\n'
                       f'📝 **ข้อความ:** {self.spam_message[:30]}{"..." if len(self.spam_message) > 30 else ""}\n'
                       f'📊 **จำนวน:** {self.spam_count}\n'
                       f'⏱️ **ระยะห่าง:** {self.spam_delay} วินาที',
            color=discord.Color.blue()
        )
        embed.add_field(name='🟢 สถานะ', value='พร้อมใช้', inline=True)
        embed.set_footer(text='⚔️ DARKCORE')
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== SLASH COMMANDS ====================

@bot.tree.command(name='ath', description='💀 ระบบยิงสแปม DM')
async def nuke_panel(interaction: discord.Interaction):
    """แสดงแผงควบคุมหลัก"""
    
    embed = discord.Embed(
        title='👽 **𝗔𝗥𝗧𝗜𝗦𝗧 𝗛𝗨𝗕**',
        description='```\n💀 ระบบยิงสแปม DM สุดโหด\n```',
        color=discord.Color.dark_red()
    )
    
    # ใส่รูปภาพแบนเนอร์
    banner_url = "https://i.ibb.co/5vQ6P8f/darkcore-banner.gif"
    embed.set_image(url=banner_url)
    
    embed.add_field(
        name='👑 เจ้าของ',
        value='`𝗔𝗥𝗧𝗜𝗦𝗧 𝗛𝗨𝗕`',
        inline=True
    )
    embed.add_field(
        name='💥 สถานะ',
        value='🟢 พร้อมใช้',
        inline=True
    )
    
    embed.set_footer(
        text='⚠️ ใช้ให้มีสติ',
        icon_url=interaction.user.display_avatar.url
    )
    
    view = DarkCorePanelView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name='attack', description='💥 ยิงสแปมไปที่เป้าหมาย')
async def quick_attack(
    interaction: discord.Interaction,
    target: str,
    message: str = 'สวัสดีครับ',
    rounds: int = 5,
    delay: float = 0.5
):
    """ยิงสแปมไปที่เป้าหมาย (ทั้งในและนอกเซิร์ฟเวอร์)"""
    
    rounds = max(1, min(400, rounds))
    delay = max(0.5, min(2.0, delay))
    
    await interaction.response.send_message(
        f'🔄 กำลังยิงไปที่ **{target}**\n'
        f'📊 {rounds} ครั้ง | ⏱️ {delay} วินาที',
        ephemeral=False
    )
    
    # ค้นหา user
    target_user = None
    
    # ตรวจสอบว่าเป็น ID
    if target.isdigit():
        try:
            target_user = await bot.fetch_user(int(target))
        except:
            pass
    
    # ถ้าไม่ใช่ ID หรือหาไม่เจอ ให้หาในเซิร์ฟเวอร์
    if not target_user:
        guild = interaction.guild
        if guild:
            for member in guild.members:
                if member.name == target or member.display_name == target:
                    target_user = member
                    break
    
    if not target_user:
        await interaction.followup.send(
            f'❌ ไม่พบผู้ใช้: **{target}**',
            ephemeral=True
        )
        return
    
    # เริ่มสแปม
    sent_count = 0
    try:
        for i in range(rounds):
            try:
                await target_user.send(message)
                sent_count += 1
                await asyncio.sleep(delay)
            except discord.Forbidden:
                await interaction.followup.send(
                    f'❌ **{target_user.name}** ปิด DM',
                    ephemeral=False
                )
                break
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    await interaction.followup.send(
                        f'⚠️ Error: {str(e)[:100]}',
                        ephemeral=True
                    )
                    break
            except Exception as e:
                await interaction.followup.send(
                    f'⚠️ Error: {str(e)[:100]}',
                    ephemeral=True
                )
                break
        
        if sent_count > 0:
            await interaction.followup.send(
                f'✅ ยิงเสร็จ!\n'
                f'👤 {target_user.name}\n'
                f'📊 {sent_count}/{rounds} ครั้ง',
                ephemeral=False
            )
    except Exception as e:
        await interaction.followup.send(
            f'❌ Error: {str(e)[:100]}',
            ephemeral=True
        )

@bot.tree.command(name='status', description='📊 ตรวจสอบสถานะบอท')
async def bot_status(interaction: discord.Interaction):
    embed = discord.Embed(
        title='📊 ATH STATUS',
        description=f'🤖 {bot.user.name}\n🆔 {bot.user.id}\n🏠 {len(bot.guilds)} เซิร์ฟเวอร์',
        color=discord.Color.blue()
    )
    embed.add_field(name='🟢 สถานะ', value='ออนไลน์', inline=True)
    embed.add_field(name='👥 ผู้ใช้', value=f'{sum(g.member_count for g in bot.guilds)} คน', inline=True)
    embed.add_field(name='📊 Ping', value=f'{round(bot.latency * 1000)}ms', inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='📚 แสดงคำสั่งทั้งหมด')
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title='📚 **ATH COMMANDS**',
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name='/ath',
        value='👽 เปิดแผงควบคุมหลัก',
        inline=False
    )
    embed.add_field(
        name='/attack <เป้า> [ข้อความ] [รอบ] [ดีเลย์]',
        value='💥 ยิงสแปม DM\nตัวเลือก: ข้อความ, รอบ(1-30), ดีเลย์(0.5-2.0)',
        inline=False
    )
    embed.add_field(
        name='/status',
        value='📊 ตรวจสอบสถานะ',
        inline=False
    )
    embed.add_field(
        name='/help',
        value='📚 แสดงคำสั่ง',
        inline=False
    )
    
    embed.set_footer(text='👽 Ath SYSTEM | 𝙰𝚛𝚝𝚒𝚜𝚝 𝚑𝚞𝚋')
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='dm', description='💬 ส่งข้อความ DM ถึงเป้าหมาย')
async def send_dm(
    interaction: discord.Interaction,
    target: str,
    message: str
):
    """ส่งข้อความ DM ถึงเป้าหมาย"""
    
    await interaction.response.send_message(
        f'📨 กำลังส่งข้อความไปที่ **{target}**...',
        ephemeral=False
    )
    
    # ค้นหา user
    target_user = None
    
    # ตรวจสอบว่าเป็น ID
    if target.isdigit():
        try:
            target_user = await bot.fetch_user(int(target))
        except:
            pass
    
    # ถ้าไม่ใช่ ID หรือหาไม่เจอ ให้หาในเซิร์ฟเวอร์
    if not target_user:
        guild = interaction.guild
        if guild:
            for member in guild.members:
                if member.name == target or member.display_name == target:
                    target_user = member
                    break
    
    if not target_user:
        await interaction.followup.send(
            f'❌ ไม่พบผู้ใช้: **{target}**',
            ephemeral=True
        )
        return
    
    try:
        await target_user.send(message)
        await interaction.followup.send(
            f'✅ ส่งข้อความถึง **{target_user.name}** สำเร็จ!',
            ephemeral=False
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f'❌ **{target_user.name}** ปิด DM',
            ephemeral=False
        )
    except Exception as e:
        await interaction.followup.send(
            f'❌ Error: {str(e)[:100]}',
            ephemeral=True
        )

# ==================== SYNC COMMANDS ====================

@bot.event
async def on_ready():
    print('='*50)
    print(f'✅ Ath Discord Bot Online!')
    print(f'🤖 Bot: {bot.user.name}')
    print(f'🆔 ID: {bot.user.id}')
    print(f'📡 Connected to {len(bot.guilds)} servers')
    print('='*50)
    
    await bot.change_presence(activity=discord.Game(name='☢️ NUKE MODE'))
    
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} slash commands')
        for cmd in synced:
            print(f'  /{cmd.name} - {cmd.description}')
    except Exception as e:
        print(f'❌ Failed to sync commands: {e}')

# ==================== RUN ====================
TOKEN = 'MTU2MjIxNzMwOTI0MDU2MTc1NA.GFI0Nz.hHKcid_4SjBVHXgtJPK47sjQI20LLcV1nPTP_M'  # <  ใส่โทเค่นบอทตรงนี้

if __name__ == '__main__':
    try:
        print('🚀 Starting NUKE Bot...')
        bot.run(TOKEN, reconnect=True)
    except discord.LoginFailure:
        print('❌ โทเค่นไม่ถูกต้อง! กรุณาตรวจสอบ Token ของคุณ')
        print('💡 ไปที่ https://discord.com/developers/applications เพื่อรับ Token ใหม่')
    except discord.ConnectionClosed:
        print('⚠️ การเชื่อมต่อถูกปิด พยายามเชื่อมต่อใหม่...')
    except KeyboardInterrupt:
        print('\n🛑 Bot ถูกหยุดโดยผู้ใช้')
    except Exception as e:
        print(f'❌ Error: {e}')
        print('💡 ตรวจสอบว่า Token ถูกต้องและ Bot มีสิทธิ์ที่เหมาะสม')
