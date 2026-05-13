import os
from collections.abc import Callable, Awaitable

import discord
from discord.ext import commands

from .modbot import Modbot
from .utils import helper_functions as hf
from cogs.utils.BotUtils import bot_utils as utils

RYRY_ID = 202995638860906496
TEST_SERVER_ID = 275146036178059265
MFA_URL_EN = "https://support.discord.com/hc/en-us/articles/219576828-Setting-up-Multi-Factor-Authentication"
MFA_URL_ES = "https://support.discord.com/hc/es/articles/219576828-Configurando-la-Autenticación-de-múltiples-factores"
DEAUTHORIZE_APPS_URL = "https://www.iorad.com/player/2100432/Discord---How-to-deauthorize-an-app-"
INTERACTION_TIMEOUT_SECONDS = 300


async def reinitialize_buttons(unbans):
    # example DB:
    # {
    # 'start_appeal_button':
    #   {986061548877410354: 1233599842983477258,
    #   1024106910225535076: 1233600145963094056,
    #   1024106387472666715: 1233600190284304414,
    #   985968511455232000: 1233600227957805158,
    #   985968434263257138: 1233600254239309895},
    # 'report_button': {554572239836545074: 1233599933563666462, 774660366620950538: 1233601399024124026},
    # 'main_start_button': {985967093411368981: 1233600929740230667}
    # }
    await unbans.bot.wait_until_ready()
    for button_name, button_dict in unbans.bot.db.get('buttons', {}).items():
        if button_name == 'start_appeal_button':
            for channel_id, msg_id in button_dict.items():
                print(f"Setting up appeal button view for {channel_id}, {msg_id}")
                await unbans.setup_appeal_button_view(channel_id, msg_id)
        
        elif button_name == 'main_start_button':
            for channel_id, msg_id in button_dict.items():
                print(f"Setting up main start button view for {channel_id}, {msg_id}")
                await unbans.setup_appeal_button_view(channel_id, msg_id)

class BanAppealForm(utils.RaiModal, title="Ban Appeal Form"):
    appeal_text_input = discord.ui.TextInput(
        label="",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=16)

    def __init__(self,
                 submit_appeal_callback: Callable[[discord.Interaction, str], Awaitable[None]],
                 locale="en"):
        super().__init__()
        self.submit_appeal_callback = submit_appeal_callback
        self.locale = locale
        self.set_modal_text()

    def set_modal_text(self):
        placeholder_text_langs = {
            'en': "Your case for being unbanned here (you can send more messages, pictures, files, etc later)",
            'es': "Su caso para ser desbaneado aquí (puede enviar más mensajes, imágenes, archivos, etc. más tarde)",
            'ja': "後でさらにメッセージ、画像、ファイルなどを送信できます。",
            'zh-CN': "稍后可以发送更多消息、图片、文件等。",
            'zh-TW': "稍後可以發送更多消息、圖片、文件等。",
        }
        self.appeal_text_input.label = "Unban Reason"
        if not self.locale.startswith("zh"):
            self.locale = self.locale.split('-')[0]  # e.g. en-US -> en, es-ES -> es, but keep zh-CN and zh-TW
        self.appeal_text_input.placeholder = placeholder_text_langs.get(self.locale, placeholder_text_langs['en'])

    async def on_submit(self, interaction: discord.Interaction):
        await self.submit_appeal_callback(interaction, self.appeal_text_input.value)

class Unbans(commands.Cog):
    """
    This cog is to manage the unbans server.

    When users are banned, if they join this server they can initiate an unban request through modbot.
    """
    
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.ban_appeal_server_id = int(os.getenv("BAN_APPEALS_GUILD_ID") or 0)

    @staticmethod
    def normalize_locale(locale: str) -> str:
        """Normalize locale strings while keeping all Chinese variants grouped under a single zh key."""
        if locale.startswith("zh"):
            return "zh"
        return locale.split('-')[0]

    @staticmethod
    def get_mfa_url(locale: str) -> str:
        if locale == "es":
            return MFA_URL_ES
        return MFA_URL_EN
    
    async def cog_load(self):
        utils.asyncio_task(reinitialize_buttons, self)
    
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if not msg.guild:
            return
        
        ban_appeal_server = self.bot.get_guild(self.ban_appeal_server_id)
        if msg.guild == ban_appeal_server and msg.author != msg.guild.me:
            if msg.channel.category.id == 985967149602439198 or msg.channel.id == 985967093411368981:
                await self.reattach_report_button(msg)  # if a mod edits one of the report info channels

    async def setup_appeal_button_view(self,
                                       msg_channel_id: int, msg_id: int = None) -> discord.Message:
        """Sets up the view for the ban appeal button"""
        channel = self.bot.get_channel(msg_channel_id)
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
            except discord.NotFound:
                msg = None
        else:
            msg = None
        
        view = utils.RaiView(timeout=0)
        button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Start ban appeal")
        view.add_item(button)
        if channel.name == 'start_here':
            button.callback = self.main_start_button_callback
        elif channel.category.name == 'servers':
            button.callback = self.start_appeal_button_callback
        
        if msg and msg.author == self.bot.user:
            sent_msg = await msg.edit(view=view)
        else:
            invisible_character = "⁣"
            sent_msg = await channel.send(invisible_character, view=view)
            
            # main appeal start button
            if channel.name == 'start_here':
                self.bot.db['buttons'].setdefault('main_start_button', {})
                self.bot.db['buttons']['main_start_button'][channel.id] = sent_msg.id
            
            # the appeal start buttons in each server's appeal channel
            elif channel.category.name == 'servers':
                self.bot.db['buttons'].setdefault('start_appeal_button', {})
                self.bot.db['buttons']["start_appeal_button"][channel.id] = sent_msg.id
        
        return sent_msg
    
    async def reattach_report_button(self, msg: discord.Message):
        """Called if a mod sends a message in the report info channel.

        This function will clear all the UI views in the channel and reattach them to the last message in channel"""
        async for m in msg.channel.history(limit=None):
            if m.author == msg.guild.me:
                await m.delete()
        
        await self.setup_appeal_button_view(msg.channel.id, msg.id)
    
    async def main_start_button_callback(self, button_interaction: discord.Interaction):
        """Perform the following steps
        1) Checks if the user is banned in some server
        2) For each server with a ban entry for the user, it will give them the role
        with a name equal to that server's ID"""
        roles = []
        for guild in self.bot.guilds:
            # Check if there's a channel in the appeals server corresponding to guild
            channel = discord.utils.find(lambda c: c.topic.split('\n')[0] == str(guild.id) if c.topic else False,
                                         button_interaction.guild.text_channels)
            if not channel:
                continue
            
            # Check if user is banned in guild
            try:
                if button_interaction.user.id == RYRY_ID and guild.id == TEST_SERVER_ID:
                    pass
                else:
                    await guild.fetch_ban(button_interaction.user)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                await button_interaction.response.send_message(f"I lack the permission to check bans on {guild.name}. "
                                                               f"In order to check this, I need `Ban Members`.")
                continue
            
            # If banned, create/add the role corresponding to guild
            else:
                try:
                    role = discord.utils.find(lambda r: r.name.startswith(str(guild.id)),
                                              button_interaction.guild.roles)
                    if not role:
                        role = await button_interaction.guild.create_role(name=str(guild.id))
                        try:
                            await channel.set_permissions(role, read_messages=True)
                        except discord.Forbidden:
                            await button_interaction.response.send_message("I lack the ability to edit permissions "
                                                                           "on channels. Please give me the "
                                                                           "`Manage Channels` permission.")
                            return
                    await button_interaction.user.add_roles(role)
                    roles.append(role)
                except discord.Forbidden:
                    await button_interaction.response.send_message("I lack the permission to manage roles in this "
                                                                   "server. Please give me that permission.")
                    return
        
        found_channels = []
        if roles:
            guild_ids = [r.name.split('_')[0] for r in roles]
            for guild_id in guild_ids:
                if found_channel := discord.utils.find(lambda c: c.topic.split('\n')[0] == str(guild_id) if c.topic else False,
                                                       button_interaction.guild.text_channels):
                    found_channels.append(found_channel)
        
        if button_interaction.user.id == RYRY_ID:
            found_channels.append(self.bot.get_channel(986061548877410354))
        
        if found_channels:
            list_of_channel_mentions = '\n- '.join([c.mention for c in found_channels])
            await button_interaction.response.send_message(f"I've found ban entries in at least one server. Please "
                                                           f"check the following channels to start a ban appeal.\n"
                                                           f"- {list_of_channel_mentions}", ephemeral=True)
        else:
            m = "You are not banned in any of the servers I currently serve on this ban appeals server. " \
                "Please check again with the mods of that server. \n\nNote if you're sure you can't join that sever, " \
                "you may be IP banned. If you've ever used any other Discord accounts before, please try to join " \
                "this server with one of those accounts and try starting the process again."
            await button_interaction.response.send_message(m, ephemeral=True)
    
    async def start_appeal_button_callback(self, button_interaction: discord.Interaction):
        """When this button is pressed, it will confirm in the language of the user client if they really wish
        to open a ban appeal"""
        locale = button_interaction.locale
        try:
            guild_id = int(button_interaction.channel.topic.split('\n')[0])
            guild = self.bot.get_guild(guild_id)
        except TypeError:
            await button_interaction.response.send_message(f"<@{self.bot.owner_id}>: Please set the topic of this "
                                                           "channel to just a guild ID and nothing else.")
            return
            
        if not guild:
            await button_interaction.response.send_message("There's been some error and I can't find this guild "
                                                           "anymore. Maybe they've kicked me or the guild has been "
                                                           "deleted. Please contact Ryan")
            return
        
        # Check if the user already is in a report / appeal somewhere
        if button_interaction.user.id in self.bot.db['reports']:
            dm_channel = button_interaction.user.dm_channel
            dm_channel_link = ''
            if dm_channel:
                dm_channel_link = f":\n{dm_channel.jump_url}"
            await button_interaction.response.send_message("You are already in a report or ban appeal somewhere, "
                                                           f"please check your DMs with me{dm_channel_link}",
                                                           ephemeral=True)
            return
        
        # Check if a user has been blocked by the guild
        blocked_users_dict = self.bot.db.get('blocked_users', {})
        if button_interaction.user.id in blocked_users_dict.get(guild.id, []):
            await button_interaction.response.send_message("This guild's appeals room has been temporarily closed "
                                                           "down. Please try again later.", ephemeral=True)
            return
        
        # Check if guild report room is set up properly
        if guild_id not in self.bot.db['guilds']:
            await button_interaction.response.send_message("The server has not properly setup their modbot room. The "
                                                           "moderators should type `_setup` in some channel on their "
                                                           "main server.")
            return
        
        # Check if user is not already unbanned
        try:
            await guild.fetch_ban(button_interaction.user)
        except discord.NotFound:
            if not button_interaction.user.id == int(os.getenv("OWNER_ID")):
                await button_interaction.response.send_message("You are not banned or already unbanned from this server.",
                                                               ephemeral=True)
                return
        
        # Create DM channel
        dm_channel = button_interaction.user.dm_channel
        if not dm_channel:
            try:
                await button_interaction.user.create_dm()
            except (discord.Forbidden, discord.HTTPException):
                pass
        dm_channel_link = ''
        if dm_channel:
            dm_channel_link = f":\n{dm_channel.jump_url}"
            
        # check if I can DM the user
        try:
            await button_interaction.user.send(None)  # purposely send "None"
        except discord.Forbidden:
            # Forbidden: 403 Forbidden (error code: 50007): Cannot send messages to this user
            error_text = ("I cannot send you DMs, please enable DMs from non-friends in your privacy settings from "
                          "this server")
            await button_interaction.response.send_message(error_text, ephemeral=True)
            return False  # cannot open DM with user
        except discord.HTTPException:
            # HTTPException: 400 Bad Request (error code: 50006): Cannot send an empty message
            pass  # DM works

        # Start ban appeal process
        self.bot.db['user_localizations'][button_interaction.user.id] = str(locale)
        locale_key = self.normalize_locale(str(locale))
        locales = {
            "en": {
                "regular_start_text": f"This will start a ban appeal with {guild.name}. Are you sure you wish to continue?",
                "regular_start_button": "Start a ban appeal",
                "yes": "Yes",
                "no": "No",
                "cancel": "Cancel",
                "canceled": "Canceled",
                "final_text": f"Please read the private message from {self.bot.user.mention}{dm_channel_link}",
                "hacked_prompt": "Was your Discord account hacked?",
                "hacked_prompt_details": "Choose one option below to continue.",
                "security_intro": "If your account was hacked, please complete these steps before appealing your ban:\n1. Change your password.\n2. Enable two-factor authentication.\n3. Remove all approved apps from your account.",
                "question_1": "Have you recovered your account and changed your password?",
                "question_2": "Have you enabled two-factor authentication?",
                "question_3": "Have you removed all approved apps from your account?",
                "security_not_ready": "Please complete all 3 safety steps first, then start the appeal again.",
                "security_complete_starting": f"Thanks. I will start your appeal now. Please read the private message from {self.bot.user.mention}{dm_channel_link}",
                "hacked_yes": "Yes, my account was hacked",
                "hacked_no": "No, it was not hacked",
                "checklist_header": "Hacked-account checklist answers:",
                "mfa_help": "2FA help",
                "apps_help": "Remove approved apps",
            },
            "es": {
                "regular_start_text": f"Esto iniciará una apelación de baneo con {guild.name}. ¿Está seguro de que desea continuar?",
                "regular_start_button": "Iniciar una apelación de expulsión",
                "yes": "Sí",
                "no": "No",
                "cancel": "Cancelar",
                "canceled": "Cancelado",
                "final_text": f"Por favor, lea el mensaje privado de {self.bot.user.mention}{dm_channel_link}.",
                "hacked_prompt": "¿Tu cuenta de Discord fue hackeada?",
                "hacked_prompt_details": "Elige una opción para continuar.",
                "security_intro": "Si tu cuenta fue hackeada, completa estos pasos antes de apelar tu baneo:\n1. Cambia tu contraseña.\n2. Activa la autenticación de dos factores.\n3. Elimina todas las aplicaciones autorizadas de tu cuenta.",
                "question_1": "¿Ya recuperaste tu cuenta y cambiaste tu contraseña?",
                "question_2": "¿Ya activaste la autenticación de dos factores?",
                "question_3": "¿Ya eliminaste todas las aplicaciones autorizadas de tu cuenta?",
                "security_not_ready": "Completa primero los 3 pasos de seguridad y luego vuelve a iniciar la apelación.",
                "security_complete_starting": f"Gracias. Ahora iniciaré tu apelación. Por favor, revisa el mensaje privado de {self.bot.user.mention}{dm_channel_link}.",
                "hacked_yes": "Sí, mi cuenta fue hackeada",
                "hacked_no": "No, no fue hackeada",
                "checklist_header": "Respuestas de la lista de seguridad por cuenta hackeada:",
                "mfa_help": "Ayuda para 2FA",
                "apps_help": "Eliminar apps autorizadas",
            },
            "ja": {
                "regular_start_text": f"これにより{guild.name}でバンの解除申請が開始されます。よろしいですか。",
                "regular_start_button": "バンの解除申請を開始",
                "yes": "はい",
                "no": "いいえ",
                "cancel": "キャンセル",
                "canceled": "中止しました。",
                "final_text": f"{self.bot.user.mention}からのメッセージをご確認ください{dm_channel_link}。",
                "hacked_prompt": "Discordアカウントは乗っ取られましたか？",
                "hacked_prompt_details": "続行するには下のボタンを選択してください。",
                "security_intro": "アカウントが乗っ取られた場合、バン解除申請の前に次を行ってください:\n1. パスワードを変更する。\n2. 二要素認証を有効にする。\n3. 承認済みアプリをすべて削除する。",
                "question_1": "アカウントを復旧し、パスワードを変更しましたか？",
                "question_2": "二要素認証を有効にしましたか？",
                "question_3": "承認済みアプリをすべて削除しましたか？",
                "security_not_ready": "先に3つの安全手順をすべて完了してから、もう一度申請を開始してください。",
                "security_complete_starting": f"ありがとうございます。今から申請を開始します。{self.bot.user.mention}からのDMをご確認ください{dm_channel_link}。",
                "hacked_yes": "はい、乗っ取られました",
                "hacked_no": "いいえ、乗っ取られていません",
                "checklist_header": "乗っ取りアカウント確認の回答:",
                "mfa_help": "2FAヘルプ",
                "apps_help": "承認済みアプリを削除",
            },
            "fr": {
                "regular_start_text": f"Cela va démarrer un appel de bannissement avec {guild.name}. Voulez-vous continuer ?",
                "regular_start_button": "Démarrer un appel de bannissement",
                "yes": "Oui",
                "no": "Non",
                "cancel": "Annuler",
                "canceled": "Annulé",
                "final_text": f"Veuillez lire le message privé de {self.bot.user.mention}{dm_channel_link}.",
                "hacked_prompt": "Votre compte Discord a-t-il été piraté ?",
                "hacked_prompt_details": "Choisissez une option ci-dessous pour continuer.",
                "security_intro": "Si votre compte a été piraté, veuillez faire ces étapes avant de faire appel:\n1. Changez votre mot de passe.\n2. Activez l’authentification à deux facteurs.\n3. Supprimez toutes les applications autorisées de votre compte.",
                "question_1": "Avez-vous récupéré votre compte et changé votre mot de passe ?",
                "question_2": "Avez-vous activé l’authentification à deux facteurs ?",
                "question_3": "Avez-vous supprimé toutes les applications autorisées de votre compte ?",
                "security_not_ready": "Veuillez d’abord terminer les 3 étapes de sécurité, puis recommencer l’appel.",
                "security_complete_starting": f"Merci. Je vais démarrer votre appel maintenant. Veuillez lire le message privé de {self.bot.user.mention}{dm_channel_link}.",
                "hacked_yes": "Oui, mon compte a été piraté",
                "hacked_no": "Non, il n’a pas été piraté",
                "checklist_header": "Réponses de la checklist de compte piraté :",
                "mfa_help": "Aide 2FA",
                "apps_help": "Supprimer les apps autorisées",
            },
            "ar": {
                "regular_start_text": f"سيؤدي هذا إلى بدء استئناف الحظر مع {guild.name}. هل تريد المتابعة؟",
                "regular_start_button": "بدء استئناف الحظر",
                "yes": "نعم",
                "no": "لا",
                "cancel": "إلغاء",
                "canceled": "تم الإلغاء",
                "final_text": f"يرجى قراءة الرسالة الخاصة من {self.bot.user.mention}{dm_channel_link}.",
                "hacked_prompt": "هل تم اختراق حسابك في Discord؟",
                "hacked_prompt_details": "اختر أحد الخيارات أدناه للمتابعة.",
                "security_intro": "إذا تم اختراق حسابك، يرجى إكمال الخطوات التالية قبل الاستئناف:\n1. غيّر كلمة المرور.\n2. فعّل المصادقة الثنائية.\n3. أزل كل التطبيقات المصرح بها من حسابك.",
                "question_1": "هل استعدت حسابك وغيّرت كلمة المرور؟",
                "question_2": "هل فعّلت المصادقة الثنائية؟",
                "question_3": "هل أزلت كل التطبيقات المصرح بها من حسابك؟",
                "security_not_ready": "يرجى إكمال خطوات الأمان الثلاث أولًا ثم ابدأ الاستئناف مرة أخرى.",
                "security_complete_starting": f"شكرًا لك. سأبدأ استئنافك الآن. يرجى قراءة الرسالة الخاصة من {self.bot.user.mention}{dm_channel_link}.",
                "hacked_yes": "نعم، تم اختراق حسابي",
                "hacked_no": "لا، لم يتم اختراقه",
                "checklist_header": "إجابات قائمة التحقق لحالة اختراق الحساب:",
                "mfa_help": "مساعدة 2FA",
                "apps_help": "إزالة التطبيقات المصرح بها",
            },
            "zh": {
                "regular_start_text": f"这将向 {guild.name} 发起封禁申诉。你确定要继续吗？",
                "regular_start_button": "开始封禁申诉",
                "yes": "是",
                "no": "否",
                "cancel": "取消",
                "canceled": "已取消",
                "final_text": f"请阅读来自 {self.bot.user.mention} 的私信{dm_channel_link}。",
                "hacked_prompt": "你的 Discord 账号被盗了吗？",
                "hacked_prompt_details": "请选择一个选项继续。",
                "security_intro": "如果你的账号被盗，请在申诉前先完成以下步骤：\n1. 修改密码。\n2. 启用双重验证。\n3. 移除账号中所有已授权应用。",
                "question_1": "你是否已经找回账号并修改密码？",
                "question_2": "你是否已经启用双重验证？",
                "question_3": "你是否已经移除所有已授权应用？",
                "security_not_ready": "请先完成这 3 个安全步骤，然后再重新开始申诉。",
                "security_complete_starting": f"谢谢。我现在将开始你的申诉。请阅读来自 {self.bot.user.mention} 的私信{dm_channel_link}。",
                "hacked_yes": "是，我的账号被盗了",
                "hacked_no": "否，没有被盗",
                "checklist_header": "账号被盗安全检查答案：",
                "mfa_help": "2FA 帮助",
                "apps_help": "移除已授权应用",
            },
        }
        text = locales.get(locale_key, locales["en"])
        mfa_url = self.get_mfa_url(locale_key)

        async def on_ban_appeal_submit(interaction: discord.Interaction, appeal_text: str):
            await interaction.response.send_message(text["final_text"], ephemeral=True)
            await self.start_ban_appeal(button_interaction.user, guild, appeal_text)

        async def open_regular_appeal_modal(confirmation_interaction: discord.Interaction):
            await confirmation_interaction.response.send_modal(BanAppealForm(on_ban_appeal_submit, str(locale)))

        async def show_normal_appeal_start(interaction: discord.Interaction):
            confirmation_button = discord.ui.Button(label=text["regular_start_button"], style=discord.ButtonStyle.primary)
            cancellation_button = discord.ui.Button(label=text["cancel"], style=discord.ButtonStyle.secondary)
            view = utils.RaiView(timeout=INTERACTION_TIMEOUT_SECONDS)
            view.add_item(confirmation_button)
            view.add_item(cancellation_button)

            async def on_timeout():
                await button_interaction.edit_original_response(view=None)

            view.on_timeout = on_timeout

            async def confirmation_callback(confirmation_interaction: discord.Interaction):
                await open_regular_appeal_modal(confirmation_interaction)

            async def cancellation_callback(cancellation_interaction: discord.Interaction):
                await cancellation_interaction.response.edit_message(content=text["canceled"], view=None)

            confirmation_button.callback = confirmation_callback
            cancellation_button.callback = cancellation_callback
            await interaction.response.edit_message(content=text["regular_start_text"], view=view)

        answers = {}
        questions = [
            ("password_changed", text["question_1"]),
            ("enabled_2fa", text["question_2"]),
            ("removed_apps", text["question_3"]),
        ]

        def resource_view(include_cancel: bool = False):
            view = utils.RaiView(timeout=INTERACTION_TIMEOUT_SECONDS)
            view.add_item(discord.ui.Button(label=text["mfa_help"], style=discord.ButtonStyle.link, url=mfa_url))
            view.add_item(discord.ui.Button(label=text["apps_help"], style=discord.ButtonStyle.link, url=DEAUTHORIZE_APPS_URL))
            if include_cancel:
                cancel_btn = discord.ui.Button(label=text["cancel"], style=discord.ButtonStyle.secondary)
                view.add_item(cancel_btn)

                async def cancel_callback(cancel_interaction: discord.Interaction):
                    await cancel_interaction.response.edit_message(content=text["canceled"], view=None)

                cancel_btn.callback = cancel_callback
            return view

        async def show_security_question(interaction: discord.Interaction, question_index: int):
            if question_index >= len(questions):
                if all(answers.values()):
                    checklist_lines = [text["checklist_header"]]
                    for answer_key, question_label in questions:
                        answer_text = text["yes"] if answers.get(answer_key) else text["no"]
                        checklist_lines.append(f"- {question_label}: {answer_text}")
                    appeal_text = "\n".join(checklist_lines)
                    await interaction.response.edit_message(content=text["security_complete_starting"], view=None)
                    await self.start_ban_appeal(button_interaction.user, guild, appeal_text)
                else:
                    await interaction.response.edit_message(
                        content=f"{text['security_not_ready']}\n\n{text['security_intro']}",
                        view=resource_view(include_cancel=True)
                    )
                return

            answer_key, question = questions[question_index]
            yes_btn = discord.ui.Button(label=text["yes"], style=discord.ButtonStyle.success)
            no_btn = discord.ui.Button(label=text["no"], style=discord.ButtonStyle.danger)
            question_view = utils.RaiView(timeout=INTERACTION_TIMEOUT_SECONDS)
            question_view.add_item(yes_btn)
            question_view.add_item(no_btn)
            if question_index == 0:
                question_view.add_item(
                    discord.ui.Button(
                        label=text["mfa_help"],
                        style=discord.ButtonStyle.link,
                        url=mfa_url
                    )
                )
                question_view.add_item(
                    discord.ui.Button(
                        label=text["apps_help"],
                        style=discord.ButtonStyle.link,
                        url=DEAUTHORIZE_APPS_URL
                    )
                )

            async def yes_callback(q_interaction: discord.Interaction):
                answers[answer_key] = True
                await show_security_question(q_interaction, question_index + 1)

            async def no_callback(q_interaction: discord.Interaction):
                answers[answer_key] = False
                await show_security_question(q_interaction, question_index + 1)

            yes_btn.callback = yes_callback
            no_btn.callback = no_callback
            await interaction.response.edit_message(
                content=f"{text['security_intro']}\n\n{question}",
                view=question_view
            )

        hacked_yes_button = discord.ui.Button(label=text["hacked_yes"], style=discord.ButtonStyle.danger)
        hacked_no_button = discord.ui.Button(label=text["hacked_no"], style=discord.ButtonStyle.success)
        hacked_cancel_button = discord.ui.Button(label=text["cancel"], style=discord.ButtonStyle.secondary)
        hacked_view = utils.RaiView(timeout=INTERACTION_TIMEOUT_SECONDS)
        hacked_view.add_item(hacked_yes_button)
        hacked_view.add_item(hacked_no_button)
        hacked_view.add_item(hacked_cancel_button)

        async def hacked_yes_callback(hacked_interaction: discord.Interaction):
            answers.clear()
            await show_security_question(hacked_interaction, 0)

        async def hacked_no_callback(hacked_interaction: discord.Interaction):
            await show_normal_appeal_start(hacked_interaction)

        async def hacked_cancel_callback(hacked_interaction: discord.Interaction):
            await hacked_interaction.response.edit_message(content=text["canceled"], view=None)

        hacked_yes_button.callback = hacked_yes_callback
        hacked_no_button.callback = hacked_no_callback
        hacked_cancel_button.callback = hacked_cancel_callback
        await button_interaction.response.send_message(
            f"{text['hacked_prompt']}\n{text['hacked_prompt_details']}",
            view=hacked_view,
            ephemeral=True
        )
    
    async def start_ban_appeal(self, user: discord.User, guild: discord.Guild, appeal_msg_text: str):
        # In case modal does not close properly but the appeal is made, prevent copies
        if user.id in self.bot.db['reports']:
            return
        # noinspection PyTypeChecker
        cog: Modbot = self.bot.get_cog("Modbot")
        await cog.start_ban_appeal_room(user, guild, appeal_text=appeal_msg_text,
                                        report_room_type="main")


async def setup(bot):
    await bot.add_cog(Unbans(bot))
