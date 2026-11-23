"""Components V2 cards for reports started in the bot's DMs."""
import asyncio
import os

import discord

from .utils import helper_functions as hf


WELCOME = (
    "__**Push this button to start.**__\n"
    "Presiona este botón para empezar.\n"
    "このボタンを押すと始まります。\n"
    "Appuie sur ce bouton pour commencer.\n"
    "اضغط على هذا الزر للبدء.\n"
    "点击此按钮开始。"
)
TOPICS = {
    "report": ("main", "report_user"),
    "account": ("main", "account_question"),
    "question": ("secondary", "server_question"),
    "voice": ("voice", "voice_issue"),
}
COPY = {
    "en": {
        "title": "Contact the moderators", "intro": "Moderators receive your draft when you select Send report.",
        "server": "Choose a server", "topic": "Choose a topic", "report": "Report a user",
        "account": "Account question", "question": "Server question", "voice": "Voice chat issue",
        "draft": "Report draft", "empty": "Send details or attach a file here to add it to your draft.",
        "anonymous": "Report anonymously", "on": "On", "off": "Off",
        "privacy": "The bot hides your account from moderators. Details you share can still identify you.",
        "send": "Send report", "edit": "Edit draft", "cancel": "Cancel",
        "none": "No shared server is available for DM reports. Contact the server’s moderators directly.",
        "expired": "This draft expired. Send another DM here to start again.",
        "canceled": "Draft canceled. Send another DM here to start again.",
        "unavailable": "That server is unavailable for reports. Send another DM here to start again.",
        "failed": "The report could not be opened. Contact the server’s moderators if you still need help.",
        "sending": "Sending your report…", "stale": "The draft changed. Open Edit draft again.",
        "limit": "Your draft is full. Edit it here or send the rest after opening the report.",
        "sent": "Report sent", "sent_anon": "Report sent anonymously",
        "connected": "New messages and attachments here go to the moderators. Replies appear here. Type `end` or `close` to close.",
        "close": "Close conversation", "confirm": "Close this conversation?", "keep": "Keep open",
        "closed": "Conversation closed", "interrupted": "Conversation interrupted",
        "attachments": "Attached items", "previous": "Previous", "next": "Next",
    },
    "es": {
        "title": "Contactar con moderación", "intro": "El equipo de moderación recibirá tu borrador cuando selecciones Enviar reporte.",
        "server": "Elige un servidor", "topic": "Elige un tema", "report": "Reportar a un usuario",
        "account": "Pregunta sobre mi cuenta", "question": "Pregunta sobre el servidor", "voice": "Problema de voz",
        "draft": "Borrador del reporte", "empty": "Envía detalles o adjunta un archivo aquí para añadirlos al borrador.",
        "anonymous": "Reportar de forma anónima", "on": "Sí", "off": "No",
        "privacy": "El bot oculta tu cuenta al equipo de moderación. Los detalles que compartas podrían identificarte.",
        "send": "Enviar reporte", "edit": "Editar borrador", "cancel": "Cancelar",
        "none": "No compartimos un servidor que acepte reportes por mensaje directo. Contacta directamente con sus moderadores.",
        "expired": "El borrador caducó. Envía otro mensaje aquí para empezar de nuevo.",
        "canceled": "Borrador cancelado. Envía otro mensaje aquí para empezar de nuevo.",
        "unavailable": "Ese servidor no está disponible. Envía otro mensaje aquí para empezar de nuevo.",
        "failed": "No se pudo abrir el reporte. Contacta a los moderadores si aún necesitas ayuda.",
        "sending": "Enviando tu reporte…", "stale": "El borrador cambió. Vuelve a abrirlo para editar.",
        "limit": "El borrador está lleno. Edítalo aquí o envía el resto después de abrir el reporte.",
        "sent": "Reporte enviado", "sent_anon": "Reporte anónimo enviado",
        "connected": "Los mensajes y archivos que envíes aquí llegan a moderación. Las respuestas aparecen aquí. Escribe `end` o `close` para cerrar.",
        "close": "Cerrar conversación", "confirm": "¿Cerrar esta conversación?", "keep": "Dejar abierta",
        "closed": "Conversación cerrada", "interrupted": "Conversación interrumpida",
        "attachments": "Archivos adjuntos y otros elementos", "previous": "Anterior", "next": "Siguiente",
    },
    "ja": {
        "title": "モデレーターに連絡する", "intro": "「通報を送信」を選ぶと、下書きがモデレーターに届きます。",
        "server": "サーバーを選択", "topic": "用件を選択", "report": "ユーザーを通報",
        "account": "アカウントについての質問", "question": "サーバーについての質問", "voice": "ボイスチャットでの問題",
        "draft": "通報の下書き", "empty": "下書きに追加する内容やファイルをこのDMに送ってください。",
        "anonymous": "匿名で通報", "on": "オン", "off": "オフ",
        "privacy": "ボットはあなたのアカウントをモデレーターに表示しません。送信内容から身元が分かる場合があります。",
        "send": "通報を送信", "edit": "下書きを編集", "cancel": "キャンセル",
        "none": "DMで通報を受け付ける共通のサーバーがありません。モデレーターに直接連絡してください。",
        "expired": "下書きの有効期限が切れました。もう一度メッセージを送ってください。",
        "canceled": "下書きを破棄しました。再開するにはメッセージを送ってください。",
        "unavailable": "このサーバーには通報できません。もう一度メッセージを送ってください。",
        "failed": "通報を開始できませんでした。必要であればモデレーターに直接連絡してください。",
        "sending": "通報を送信しています…", "stale": "下書きが更新されました。もう一度編集画面を開いてください。",
        "limit": "下書きの上限に達しました。編集するか、通報後に続きを送ってください。",
        "sent": "通報を送信しました", "sent_anon": "匿名で通報を送信しました",
        "connected": "ここで送信したメッセージやファイルはモデレーターに届き、返信もここに届きます。`end` または `close` で終了できます。",
        "close": "会話を終了", "confirm": "会話を終了しますか？", "keep": "会話を続ける",
        "closed": "会話を終了しました", "interrupted": "会話が中断されました",
        "attachments": "添付アイテム", "previous": "前へ", "next": "次へ",
    },
    "fr": {
        "title": "Contacter la modération", "intro": "La modération recevra ton brouillon quand tu cliqueras sur Envoyer.",
        "server": "Choisir un serveur", "topic": "Choisir un sujet", "report": "Signaler un utilisateur",
        "account": "Question sur mon compte", "question": "Question sur le serveur", "voice": "Problème en vocal",
        "draft": "Brouillon", "empty": "Envoie les détails ou joins un fichier ici pour compléter ton brouillon.",
        "anonymous": "Envoyer anonymement", "on": "Oui", "off": "Non",
        "privacy": "Le bot masque ton compte à la modération. Les informations que tu partages peuvent t’identifier.",
        "send": "Envoyer", "edit": "Modifier le brouillon", "cancel": "Annuler",
        "none": "Aucun serveur commun n’accepte les signalements par message privé. Contacte directement la modération.",
        "expired": "Ce brouillon a expiré. Envoie un autre message ici pour recommencer.",
        "canceled": "Brouillon annulé. Envoie un autre message ici pour recommencer.",
        "unavailable": "Ce serveur n’est pas disponible. Envoie un autre message ici pour recommencer.",
        "failed": "Impossible d’ouvrir le signalement. Contacte la modération si tu as encore besoin d’aide.",
        "sending": "Envoi en cours…", "stale": "Le brouillon a changé. Rouvre la fenêtre de modification.",
        "limit": "Le brouillon est plein. Modifie-le ou envoie la suite une fois la conversation ouverte.",
        "sent": "Signalement envoyé", "sent_anon": "Signalement anonyme envoyé",
        "connected": "Tes messages et fichiers sont envoyés à la modération. Les réponses apparaissent ici. Tape `end` ou `close` pour fermer.",
        "close": "Fermer la conversation", "confirm": "Fermer cette conversation ?", "keep": "Garder ouverte",
        "closed": "Conversation fermée", "interrupted": "Conversation interrompue",
        "attachments": "Pièces jointes", "previous": "Précédent", "next": "Suivant",
    },
    "ar": {
        "title": "التواصل مع المشرفين", "intro": "سيتلقى المشرفون مسودتك عندما تختار إرسال البلاغ.",
        "server": "اختر خادمًا", "topic": "اختر موضوعًا", "report": "الإبلاغ عن مستخدم",
        "account": "سؤال عن حسابي", "question": "سؤال عن الخادم", "voice": "مشكلة في قناة صوتية",
        "draft": "مسودة البلاغ", "empty": "أرسل التفاصيل أو أرفق ملفًا هنا لإضافته إلى مسودتك.",
        "anonymous": "إرسال البلاغ دون إظهار هويتي", "on": "نعم", "off": "لا",
        "privacy": "يخفي البوت حسابك عن المشرفين. قد تكشف التفاصيل التي تشاركها عن هويتك.",
        "send": "إرسال البلاغ", "edit": "تعديل المسودة", "cancel": "إلغاء",
        "none": "لا يوجد خادم مشترك يقبل البلاغات عبر الرسائل الخاصة. تواصل مع مشرفي الخادم مباشرةً.",
        "expired": "انتهت صلاحية المسودة. أرسل رسالة أخرى هنا للبدء من جديد.",
        "canceled": "أُلغيت المسودة. أرسل رسالة أخرى هنا للبدء من جديد.",
        "unavailable": "لا يمكن إرسال بلاغ إلى هذا الخادم. أرسل رسالة أخرى هنا للبدء من جديد.",
        "failed": "تعذّر فتح البلاغ. تواصل مع المشرفين إذا كنت لا تزال بحاجة إلى المساعدة.",
        "sending": "جارٍ إرسال البلاغ…", "stale": "تغيّرت المسودة. افتح نافذة التعديل من جديد.",
        "limit": "بلغت المسودة الحد الأقصى. عدّلها أو أرسل الباقي بعد فتح البلاغ.",
        "sent": "تم إرسال البلاغ", "sent_anon": "تم إرسال البلاغ دون إظهار هويتك",
        "connected": "تصل رسائلك ومرفقاتك إلى المشرفين، وتظهر ردودهم هنا. اكتب `end` أو `close` لإغلاق المحادثة.",
        "close": "إغلاق المحادثة", "confirm": "هل تريد إغلاق المحادثة؟", "keep": "إبقاء المحادثة مفتوحة",
        "closed": "تم إغلاق المحادثة", "interrupted": "انقطعت المحادثة",
        "attachments": "المرفقات", "previous": "السابق", "next": "التالي",
    },
    "zh": {
        "title": "联系管理员", "intro": "选择发送举报后，管理员会收到你的草稿。",
        "server": "选择服务器", "topic": "选择主题", "report": "举报用户",
        "account": "账号问题", "question": "服务器问题", "voice": "语音频道问题",
        "draft": "举报草稿", "empty": "在这里发送详细信息或附件，将其添加到草稿。",
        "anonymous": "匿名举报", "on": "开启", "off": "关闭",
        "privacy": "机器人会向管理员隐藏你的账号。你分享的内容仍可能透露你的身份。",
        "send": "发送举报", "edit": "编辑草稿", "cancel": "取消",
        "none": "没有接受私信举报的共同服务器。请直接联系服务器管理员。",
        "expired": "草稿已过期。在这里再发送一条消息即可重新开始。",
        "canceled": "草稿已取消。在这里再发送一条消息即可重新开始。",
        "unavailable": "此服务器暂无法接收举报。在这里再发送一条消息即可重新开始。",
        "failed": "无法创建举报。如仍需帮助，请联系服务器管理员。",
        "sending": "正在发送举报…", "stale": "草稿已更新，请重新打开编辑窗口。",
        "limit": "草稿已满。请编辑草稿，或在创建举报后发送剩余内容。",
        "sent": "举报已发送", "sent_anon": "匿名举报已发送",
        "connected": "你在这里发送的消息和附件会转交给管理员，回复也会显示在这里。输入 `end` 或 `close` 可关闭对话。",
        "close": "关闭对话", "confirm": "要关闭此对话吗？", "keep": "保持对话开启",
        "closed": "对话已关闭", "interrupted": "对话已中断",
        "attachments": "附件", "previous": "上一页", "next": "下一页",
    },
}


def card_copy(locale):
    return COPY.get(str(locale).split("-")[0], COPY["en"])


def card(*items):
    return discord.ui.Container(*items)


def display(text):
    return discord.ui.TextDisplay(text)


def button(label, callback, *, style=discord.ButtonStyle.secondary, disabled=False):
    item = discord.ui.Button(label=label, style=style, disabled=disabled)
    item.callback = callback
    return item


def status_card(text):
    return discord.ui.LayoutView().add_item(card(display(text)))


class DraftModal(discord.ui.Modal):
    def __init__(self, intake):
        super().__init__(title=intake.copy["edit"], timeout=300)
        self.intake = intake
        self.revision = intake.revision
        self.draft = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            default=intake.draft, required=False, max_length=4000,
        )
        self.add_item(discord.ui.Label(text=intake.copy["draft"], component=self.draft))

    async def on_submit(self, interaction):
        await interaction.response.defer()
        async with self.intake.lock:
            if not self.intake.active or self.revision != self.intake.revision:
                await interaction.followup.send(
                    self.intake.copy["expired"] if not self.intake.active else self.intake.copy["stale"],
                    ephemeral=True,
                )
                return
            self.intake.draft = self.draft.value
            self.intake.revision += 1
            await self.intake.refresh()


class IntakeView(discord.ui.LayoutView):
    def __init__(self, intake):
        super().__init__(timeout=300)
        self.intake = intake

    async def interaction_check(self, interaction):
        return interaction.user.id == self.intake.user.id

    async def on_timeout(self):
        async with self.intake.lock:
            if self.intake.active and self.intake.view is self:
                await self.intake.finish(self.intake.copy["expired"])


class ReportIntake:
    def __init__(self, cog, message):
        self.cog = cog
        self.bot = cog.bot
        self.user = message.author
        self.channel = message.channel
        self.lock = asyncio.Lock()
        self.copy = card_copy(hf.get_user_locale(self.user.id))
        self.view = IntakeView(self)
        self.message = None
        self.guild_ids = []
        self.guild_id = None
        self.page = 0
        self.topic = None
        self.anonymous = False
        self.draft = "" if message.content.strip().casefold() in {"hi", "hey", "hello", "hola", "こんにちは"} else message.content
        self.messages = [message]
        self.revision = 0

    @property
    def active(self):
        return self.cog.intakes.get(self.user.id) is self

    def eligible(self, guild):
        return (
            guild is not None
            and guild.id != int(os.getenv("BAN_APPEALS_GUILD_ID") or 0)
            and self.bot.db["guilds"].get(guild.id, {}).get("channel")
            and guild.get_member(self.user.id) is not None
            and self.user.id not in self.bot.db.get("blocked_users", {}).get(guild.id, ())
        )

    async def welcome(self):
        self.view.add_item(card(display(WELCOME), discord.ui.ActionRow(
            button("Push here", self.begin, style=discord.ButtonStyle.primary),
        )))
        self.message = await self.channel.send(view=self.view)

    async def begin(self, interaction):
        await interaction.response.defer()
        async with self.lock:
            if not self.active or self.message.id != interaction.message.id:
                return
            locale = str(interaction.locale).split("-")[0]
            self.copy = card_copy(locale)
            self.bot.db.setdefault("user_localizations", {})[self.user.id] = locale
            await hf.dump_json()
            guilds = sorted((guild for guild in self.bot.guilds if self.eligible(guild)),
                            key=lambda guild: (guild.name.casefold(), guild.id))
            self.guild_ids = [guild.id for guild in guilds]
            if len(guilds) == 1:
                self.guild_id = guilds[0].id

            try:
                await self.message.delete()
            except discord.NotFound:
                pass
            self.view.stop()
            if not guilds:
                self.cog.intakes.pop(self.user.id, None)
                await self.channel.send(view=status_card(self.copy["none"]))
                return
            self.view = IntakeView(self)
            self.build_form()
            try:
                self.message = await self.channel.send(view=self.view, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                self.view.stop()
                self.cog.intakes.pop(self.user.id, None)
                raise

    def build_form(self):
        copy = self.copy
        items = [display(f"## {copy['title']}\n{copy['intro']}")]
        if len(self.guild_ids) == 1:
            guild = self.bot.get_guild(self.guild_id)
            if guild is not None:
                items.append(display(discord.utils.escape_markdown(guild.name)))
        else:
            guilds = [self.bot.get_guild(guild_id) for guild_id in self.guild_ids[self.page:self.page + 25]]
            options = [discord.SelectOption(label=guild.name[:100], value=str(guild.id),
                                            default=guild.id == self.guild_id) for guild in guilds if guild]
            if options:
                select = discord.ui.Select(placeholder=copy["server"], options=options)
                select.callback = self.select_guild
                items.append(discord.ui.ActionRow(select))
            if len(self.guild_ids) > 25:
                items.append(discord.ui.ActionRow(
                    button(copy["previous"], self.previous_page, disabled=self.page == 0),
                    button(copy["next"], self.next_page, disabled=self.page + 25 >= len(self.guild_ids)),
                ))
        topic = discord.ui.Select(placeholder=copy["topic"], options=[
            discord.SelectOption(label=copy[key], value=key, default=self.topic == key) for key in TOPICS
        ])
        topic.callback = self.select_topic
        summary = discord.utils.escape_markdown(self.draft.strip())
        if len(summary) > 2800:
            summary = summary[:2800] + "…"
        attachment_count = sum(len(msg.attachments) + len(msg.stickers) for msg in self.messages)
        items.extend([
            discord.ui.ActionRow(topic),
            discord.ui.Separator(),
            display(f"**{copy['draft']}**\n{summary or copy['empty']}"),
        ])
        if attachment_count:
            items.append(display(f"{copy['attachments']} · {attachment_count}"))
        anonymous_label = f"{copy['anonymous']} · {copy['on' if self.anonymous else 'off']}"
        items.append(discord.ui.ActionRow(button(
            anonymous_label, self.toggle_anonymous,
            style=discord.ButtonStyle.success if self.anonymous else discord.ButtonStyle.secondary,
        )))
        if self.anonymous:
            items.append(display(f"-# {copy['privacy']}"))
        items.append(discord.ui.ActionRow(
            button(copy["send"], self.submit, style=discord.ButtonStyle.primary,
                   disabled=not (self.guild_id and self.topic and self.has_content())),
            button(copy["edit"], self.edit),
            button(copy["cancel"], self.cancel),
        ))
        self.view.clear_items()
        self.view.add_item(card(*items))

    def has_content(self):
        return self.draft.strip() or any(
            msg.attachments or msg.stickers or (msg.embeds and not self.anonymous) for msg in self.messages
        )

    async def refresh(self):
        self.build_form()
        await self.message.edit(view=self.view, allowed_mentions=discord.AllowedMentions.none())

    async def add_message(self, message):
        async with self.lock:
            if not self.active:
                return False
            draft = "\n".join(part for part in (self.draft, message.content) if part)
            if len(draft) > 4000 or len(self.messages) >= 20:
                await self.channel.send(self.copy["limit"])
            else:
                self.draft = draft
                self.messages.append(message)
                self.revision += 1
                if self.guild_ids:
                    await self.refresh()
            return True

    async def update(self, interaction, *, guild_id=None, topic=None, page_delta=0, toggle=False):
        await interaction.response.defer()
        async with self.lock:
            if self.active:
                if guild_id in self.guild_ids:
                    self.guild_id = guild_id
                if topic in TOPICS:
                    self.topic = topic
                if page_delta:
                    self.page = max(0, min(self.page + page_delta, (len(self.guild_ids) - 1) // 25 * 25))
                if toggle:
                    self.anonymous = not self.anonymous
                await self.refresh()

    async def select_guild(self, interaction):
        await self.update(interaction, guild_id=int(interaction.data["values"][0]))

    async def select_topic(self, interaction):
        await self.update(interaction, topic=interaction.data["values"][0])

    async def previous_page(self, interaction):
        await self.update(interaction, page_delta=-25)

    async def next_page(self, interaction):
        await self.update(interaction, page_delta=25)

    async def toggle_anonymous(self, interaction):
        await self.update(interaction, toggle=True)

    async def edit(self, interaction):
        if self.lock.locked():
            await interaction.response.defer()
            return
        async with self.lock:
            if self.active:
                await interaction.response.send_modal(DraftModal(self))
            else:
                await interaction.response.defer()

    async def cancel(self, interaction):
        await interaction.response.defer()
        async with self.lock:
            if self.active:
                await self.finish(self.copy["canceled"])

    async def finish(self, text=None):
        self.cog.intakes.pop(self.user.id, None)
        self.view.stop()
        if text is not None:
            try:
                await self.message.edit(view=status_card(text))
            except discord.NotFound:
                pass

    async def submit(self, interaction):
        await interaction.response.defer()
        async with self.lock:
            if not self.active:
                return
            guild = self.bot.get_guild(self.guild_id) if self.guild_id else None
            if (not self.eligible(guild) or self.user.id in self.bot.db["reports"]
                    or self.user.id in self.cog.opening_reports):
                await self.finish(self.copy["unavailable"])
                return
            if self.topic not in TOPICS or not self.has_content():
                return
            # Once a moderator thread may exist, retire this draft to avoid submitting it twice.
            self.view.stop()
            self.cog.opening_reports.add(self.user.id)
            success = False
            try:
                await self.message.edit(view=status_card(self.copy["sending"]))
                room_type, report_kind = TOPICS[self.topic]
                success = await self.cog.start_report_room(
                    self.user, guild, self.messages, self.draft, room_type,
                    report_kind=report_kind, anonymous=self.anonymous, dm_card_id=self.message.id,
                )
            finally:
                self.cog.opening_reports.discard(self.user.id)
                await self.finish()
                report = self.bot.db["reports"].get(self.user.id)
                if success and report:
                    view = connected_card(self.cog, self.copy, self.anonymous)
                    # The cog's persistent handler owns close clicks, including after a reload.
                    view.stop()
                    await self.message.edit(view=view)
                    if self.bot.db["reports"].get(self.user.id) is not report:
                        await self.cog.update_dm_report_card(self.channel, self.user, report, error=False)
                elif not success:
                    await self.message.edit(view=status_card(self.copy["failed"]))


class CloseReportView(discord.ui.LayoutView):
    def __init__(self, cog, label="Close conversation", content=None):
        super().__init__(timeout=None)
        self.cog = cog
        close = discord.ui.Button(label=label, style=discord.ButtonStyle.danger, custom_id="dm-report:close")
        close.callback = self.ask
        row = discord.ui.ActionRow(close)
        self.add_item(card(display(content), row) if content else card(row))

    async def ask(self, interaction):
        copy = card_copy(hf.get_user_locale(interaction.user.id))
        report = self.cog.bot.db["reports"].get(interaction.user.id)
        if not report or report.get("dm_card_id") != interaction.message.id:
            await interaction.response.send_message(copy["closed"], ephemeral=True)
            return

        async def confirm(result):
            await result.response.defer()
            await self.cog.close_dm_report(result.user, interaction.channel, report)
            await result.delete_original_response()

        async def cancel(result):
            await result.response.defer()
            await result.delete_original_response()

        view = discord.ui.View(timeout=60)
        view.add_item(button(copy["close"], confirm, style=discord.ButtonStyle.danger))
        view.add_item(button(copy["keep"], cancel))
        await interaction.response.send_message(copy["confirm"], view=view, ephemeral=True)


def connected_card(cog, copy, anonymous):
    title = copy["sent_anon" if anonymous else "sent"]
    return CloseReportView(cog, copy["close"], f"## {title}\n{copy['connected']}")
