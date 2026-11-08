//! A colony's alert settings: whether Sentinel pings you when the colony hits a real blocker, on
//! Telegram or Slack, where, who may answer, and how long it waits first. The body of a tab in the
//! colony's side panel. Mirrors `frontend/src/components/SentinelSection.tsx`.

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use crate::api::{Api, api, encode};
use crate::pages::{flag, text};
use crate::{bg, ui};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Channel {
    Telegram,
    Slack,
}

impl Channel {
    const ALL: [Channel; 2] = [Channel::Telegram, Channel::Slack];

    fn parse(key: &str) -> Option<Self> {
        match key {
            "telegram" => Some(Channel::Telegram),
            "slack" => Some(Channel::Slack),
            _ => None,
        }
    }

    /// As the server names it.
    fn key(self) -> &'static str {
        match self {
            Channel::Telegram => "telegram",
            Channel::Slack => "slack",
        }
    }

    fn name(self) -> &'static str {
        match self {
            Channel::Telegram => "Telegram",
            Channel::Slack => "Slack",
        }
    }

    fn icon(self) -> IconName {
        match self {
            Channel::Telegram => IconName::Send,
            Channel::Slack => IconName::Hash,
        }
    }

    /// Where to send, as the server takes it.
    fn target(self, destination: &str) -> Value {
        match self {
            Channel::Telegram => json!({ "chat_id": destination }),
            Channel::Slack => json!({ "channel": destination }),
        }
    }

    /// The chat id or Slack channel out of a saved target.
    fn destination(self, target: &Value) -> String {
        text(
            target,
            match self {
                Channel::Telegram => "chat_id",
                Channel::Slack => "channel",
            },
        )
    }

    /// Whether the server holds its token(s), from `{telegram{configured}, slack{bot, app}}`.
    fn connected(self, creds: &Value) -> bool {
        match self {
            Channel::Telegram => flag(&creds["telegram"], "configured"),
            Channel::Slack => flag(&creds["slack"], "bot") && flag(&creds["slack"], "app"),
        }
    }

    /// Where the token is made. The panel offers it to copy, as it opens no browser.
    fn link(self) -> &'static str {
        match self {
            Channel::Telegram => "https://t.me/BotFather",
            Channel::Slack => "https://api.slack.com/apps",
        }
    }

    fn steps(self) -> &'static [&'static str] {
        match self {
            Channel::Telegram => &[
                "In Telegram, open @BotFather and send /newbot.",
                "Pick a name, then a username that ends in \"bot\".",
                "Paste the token it sends back.",
            ],
            Channel::Slack => &[
                "On the Slack apps page, create an app from scratch in your workspace.",
                "Under Basic Information, make an app-level token with connections:write (xapp-…).",
                "Under OAuth & Permissions, add the chat:write bot scope and install the app.",
                "Copy the bot token (xoxb-…), and turn on Socket Mode.",
            ],
        }
    }
}

/// Why Sentinel can't be turned on for a channel yet, if it can't.
fn missing(channel: Channel, connected: bool, destination: &str) -> Option<&'static str> {
    let has_destination = !destination.trim().is_empty();
    match (channel, connected, has_destination) {
        (_, true, true) => None,
        (Channel::Telegram, false, false) => Some("Connect a bot and add a chat id below first."),
        (Channel::Telegram, false, true) => Some("Connect a bot below first."),
        (Channel::Telegram, true, false) => Some("Add a chat id below first."),
        (Channel::Slack, false, false) => Some("Connect a Slack app and add a channel id below first."),
        (Channel::Slack, false, true) => Some("Connect a Slack app below first."),
        (Channel::Slack, true, false) => Some("Add a channel id below first."),
    }
}

/// The allowlist as typed: one id per line (commas work too), blanks and repeats dropped.
fn parse_allowlist(typed: &str) -> Vec<String> {
    let mut ids: Vec<String> = Vec::new();
    for id in typed.split(['\n', ',']).map(str::trim).filter(|id| !id.is_empty()) {
        if !ids.iter().any(|known| known == id) {
            ids.push(id.to_string());
        }
    }
    ids
}

/// Seconds as the minutes field shows them: whole minutes plainly, else to two places.
fn minutes_text(seconds: Option<f64>) -> String {
    let Some(seconds) = seconds else { return String::new() };
    let minutes = seconds / 60.0;
    if (minutes - minutes.round()).abs() < 1e-9 {
        format!("{}", minutes.round() as i64)
    } else {
        format!("{minutes:.2}").trim_end_matches('0').trim_end_matches('.').to_string()
    }
}

/// The minutes as typed, in whole seconds; empty means the default for all colonies.
fn parse_minutes(typed: &str) -> Result<Option<f64>, String> {
    let typed = typed.trim();
    if typed.is_empty() {
        return Ok(None);
    }
    match typed.parse::<f64>() {
        Ok(minutes) if minutes.is_finite() && minutes > 0.0 => Ok(Some((minutes * 60.0).round().max(1.0))),
        _ => Err("Minutes must be a number above 0, or empty for the default.".into()),
    }
}

/// What Detect found, as a line: the chat, and who was added to the repliers.
fn detected_note(found: &Value) -> String {
    let either = |a: &str, b: &str| Some(text(found, a)).filter(|s| !s.is_empty()).unwrap_or_else(|| text(found, b));
    let (chat, sender) = (either("chat_title", "chat_id"), either("sender_name", "sender_id"));
    if sender.is_empty() {
        format!("Found {chat}.")
    } else {
        format!("Found {chat}, and added {sender} to who can reply.")
    }
}

/// Check the tokens with the channel, then save them, so a mistyped token isn't kept. Returns who
/// it connected as.
fn connect_channel(api: &Api, channel: Channel, tokens: &[String]) -> anyhow::Result<String> {
    match channel {
        Channel::Telegram => {
            let check = api.post("/sentinel/telegram/validate", json!({ "token": tokens[0] }))?;
            if !flag(&check, "ok") {
                anyhow::bail!("Telegram didn't accept that token: {}", text(&check, "error"));
            }
            api.post("/credentials", json!({ "credential_id": "telegram", "keys": { "bot_token": tokens[0] } }))?;
            let username = text(&check, "bot_username");
            Ok(if username.is_empty() { text(&check, "bot_name") } else { format!("@{username}") })
        }
        Channel::Slack => {
            let check = api.post("/sentinel/slack/validate", json!({ "token": tokens[0] }))?;
            if !flag(&check, "ok") {
                anyhow::bail!("Slack didn't accept the bot token: {}", text(&check, "error"));
            }
            api.post("/credentials", json!({ "credential_id": "slack", "keys": { "access_token": tokens[0] } }))?;
            api.post("/credentials", json!({ "credential_id": "slack_app", "keys": { "access_token": tokens[1] } }))?;
            Ok(text(&check, "team"))
        }
    }
}

/// The settings as the PUT takes them.
#[derive(Debug, PartialEq)]
struct Draft {
    enabled: bool,
    channel: Option<String>,
    target: Value,
    allowlist: Vec<String>,
    /// How long the colony may sit idle before Sentinel checks on it; `None` is the default for all colonies.
    seconds: Option<f64>,
}

impl Draft {
    /// The settings as `GET …/notifications` returns them.
    fn of(config: &Value) -> Self {
        Draft {
            enabled: flag(config, "sentinel_enabled"),
            channel: config["channel"].as_str().map(str::to_string),
            target: if config["target"].is_object() { config["target"].clone() } else { json!({}) },
            allowlist: config["allowlist"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|id| id.as_str().map(str::to_string).unwrap_or_else(|| id.to_string()))
                .collect(),
            seconds: config["classify_after_seconds"].as_f64(),
        }
    }

    fn body(&self) -> Value {
        json!({
            "sentinel_enabled": self.enabled,
            "channel": self.channel,
            "target": self.target,
            "allowlist": self.allowlist,
            "classify_after_seconds": self.seconds,
        })
    }
}

pub struct SentinelPanel {
    colony: String,
    /// The settings as last loaded or saved.
    saved: Option<Result<Value, String>>,
    /// Which tokens the server holds: `{telegram{configured}, slack{bot, app}}`.
    creds: Value,
    /// `None` while the colony uses a channel this panel doesn't offer, i.e. the built-in Hive inbox.
    channel: Option<Channel>,
    enabled: bool,
    chat_id: Entity<InputState>,
    slack_channel: Entity<InputState>,
    allowlist: Entity<TextareaState>,
    minutes: Entity<InputState>,
    /// Telegram's bot token, then Slack's bot and app-level tokens.
    tokens: [Entity<InputState>; 3],
    /// The token form is open on a connected channel, to replace its tokens.
    replacing: bool,
    connecting: bool,
    /// What the last connect said (who it connected as, or why not), for its channel.
    connected: Option<(Channel, Result<String, String>)>,
    detecting: bool,
    detected: Option<Result<String, String>>,
    testing: bool,
    tested: Option<(Channel, Result<String, String>)>,
    saving: bool,
    save_note: Option<Result<String, String>>,
    /// The link just copied, so its button can say so.
    copied: Option<&'static str>,
    tasks: Vec<Task<()>>,
}

impl SentinelPanel {
    pub fn new(colony: String, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let field = |hint: &'static str, masked: bool, window: &mut Window, cx: &mut Context<Self>| {
            let state = cx.new(|cx| InputState::new(window, cx).placeholder(hint).masked(masked));
            cx.observe(&state, |_, _, cx| cx.notify()).detach();
            state
        };
        let chat_id = field("Chat id, e.g. 123456789", false, window, cx);
        let slack_channel = field("Channel id, e.g. C0123ABC456", false, window, cx);
        let tokens = [
            field("Bot token (123456:ABC-DEF…)", true, window, cx),
            field("Bot token (xoxb-…)", true, window, cx),
            field("App-level token (xapp-…)", true, window, cx),
        ];
        let minutes = cx.new(|cx| {
            InputState::new(window, cx)
                .placeholder("Default")
                .validate(|typed, _| typed.len() <= 8 && typed.chars().all(|c| c.is_ascii_digit() || c == '.'))
        });
        cx.observe(&minutes, |_, _, cx| cx.notify()).detach();
        let allowlist = cx.new(|cx| TextareaState::new(window, cx).auto_grow(2, 6).placeholder("One user id per line"));
        cx.observe(&allowlist, |_, _, cx| cx.notify()).detach();
        let mut panel = Self {
            colony,
            saved: None,
            creds: Value::Null,
            channel: None,
            enabled: false,
            chat_id,
            slack_channel,
            allowlist,
            minutes,
            tokens,
            replacing: false,
            connecting: false,
            connected: None,
            detecting: false,
            detected: None,
            testing: false,
            tested: None,
            saving: false,
            save_note: None,
            copied: None,
            tasks: Vec::new(),
        };
        panel.load(window, cx);
        panel
    }

    fn path(&self) -> String {
        format!("/colony/{}/notifications", encode(&self.colony))
    }

    fn load(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let (api, path) = (api(cx), self.path());
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.get(&path),
            |this: &mut Self, loaded, window, cx| match loaded {
                Ok(config) => {
                    this.creds = config["credentials"].clone();
                    this.show(config, window, cx);
                }
                Err(e) => this.saved = Some(Err(e.to_string())),
            },
        ));
    }

    fn load_creds(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/sentinel/credentials"),
            // A failed re-read leaves the last status; a connect that just worked still counts.
            |this: &mut Self, status, _| {
                if let Ok(status) = status {
                    this.creds = status;
                }
            },
        ));
    }

    /// Put the settings the server holds into the fields.
    fn show(&mut self, config: Value, window: &mut Window, cx: &mut Context<Self>) {
        let draft = Draft::of(&config);
        self.channel = draft.channel.as_deref().and_then(Channel::parse);
        self.enabled = draft.enabled;
        for channel in Channel::ALL {
            let value = if self.channel == Some(channel) { channel.destination(&draft.target) } else { String::new() };
            self.destination_field(channel).update(cx, |s, cx| s.set_value(value, window, cx));
        }
        self.allowlist.update(cx, |s, cx| s.set_value(draft.allowlist.join("\n"), window, cx));
        self.minutes.update(cx, |s, cx| s.set_value(minutes_text(draft.seconds), window, cx));
        self.saved = Some(Ok(config));
    }

    fn destination_field(&self, channel: Channel) -> &Entity<InputState> {
        match channel {
            Channel::Telegram => &self.chat_id,
            Channel::Slack => &self.slack_channel,
        }
    }

    fn destination(&self, channel: Channel, cx: &App) -> String {
        self.destination_field(channel).read(cx).value().trim().to_string()
    }

    fn token_fields(&self, channel: Channel) -> &[Entity<InputState>] {
        match channel {
            Channel::Telegram => &self.tokens[..1],
            Channel::Slack => &self.tokens[1..],
        }
    }

    fn is_connected(&self, channel: Channel) -> bool {
        channel.connected(&self.creds) || matches!(&self.connected, Some((c, Ok(_))) if *c == channel)
    }

    fn blocker(&self, channel: Channel, cx: &App) -> Option<&'static str> {
        missing(channel, self.is_connected(channel), &self.destination(channel, cx))
    }

    /// The settings as the fields have them.
    fn draft(&self, saved: &Value, cx: &App) -> Result<Draft, String> {
        let seconds = parse_minutes(&self.minutes.read(cx).value())?;
        let allowlist = parse_allowlist(&self.allowlist.read(cx).value());
        Ok(match self.channel {
            Some(channel) => Draft {
                enabled: self.enabled && self.blocker(channel, cx).is_none(),
                channel: Some(channel.key().into()),
                target: channel.target(&self.destination(channel, cx)),
                allowlist,
                seconds,
            },
            // A channel this panel doesn't offer is kept as it is, with its target.
            None => Draft { enabled: self.enabled, allowlist, seconds, ..Draft::of(saved) },
        })
    }

    fn pick(&mut self, channel: Channel, cx: &mut Context<Self>) {
        if self.channel != Some(channel) {
            self.channel = Some(channel);
            self.replacing = false;
            self.detected = None;
        }
        cx.notify();
    }

    fn connect(&mut self, channel: Channel, window: &mut Window, cx: &mut Context<Self>) {
        let fields = self.token_fields(channel).to_vec();
        let tokens: Vec<String> = fields.iter().map(|f| f.read(cx).value().trim().to_string()).collect();
        if tokens.iter().any(String::is_empty) {
            let problem = if tokens.len() > 1 { "Paste both tokens." } else { "Paste the token." };
            self.connected = Some((channel, Err(problem.into())));
            cx.notify();
            return;
        }
        self.connecting = true;
        self.connected = None;
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || connect_channel(&api, channel, &tokens),
            move |this: &mut Self, done, window, cx| {
                this.connecting = false;
                if done.is_ok() {
                    for field in &fields {
                        field.update(cx, |s, cx| s.set_value("", window, cx));
                    }
                    this.replacing = false;
                    this.load_creds(cx);
                }
                this.connected = Some((channel, done.map_err(|e| e.to_string())));
            },
        ));
        cx.notify();
    }

    fn detect(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.detecting = true;
        self.detected = None;
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.post("/sentinel/telegram/detect-chat", json!({})),
            |this: &mut Self, found, window, cx| {
                this.detecting = false;
                this.detected = Some(match found {
                    Ok(found) if flag(&found, "ok") => {
                        this.take_detected(&found, window, cx);
                        Ok(detected_note(&found))
                    }
                    Ok(found) => Err(Some(text(&found, "error"))
                        .filter(|e| !e.is_empty())
                        .unwrap_or_else(|| "No message yet. Send your bot any message, then try again.".into())),
                    Err(e) => Err(e.to_string()),
                });
            },
        ));
        cx.notify();
    }

    /// Fill in the chat Detect found, and let its sender reply.
    fn take_detected(&mut self, found: &Value, window: &mut Window, cx: &mut Context<Self>) {
        let chat_id = text(found, "chat_id");
        if !chat_id.is_empty() {
            self.chat_id.update(cx, |s, cx| s.set_value(chat_id, window, cx));
        }
        let sender = text(found, "sender_id");
        let mut ids = parse_allowlist(&self.allowlist.read(cx).value());
        if !sender.is_empty() && !ids.contains(&sender) {
            ids.push(sender);
            self.allowlist.update(cx, |s, cx| s.set_value(ids.join("\n"), window, cx));
        }
    }

    fn test(&mut self, cx: &mut Context<Self>) {
        let Some(channel) = self.channel else { return };
        // The fields, not what's saved, so a destination can be tried before saving it.
        let body = json!({ "channel": channel.key(), "target": channel.target(&self.destination(channel, cx)) });
        self.testing = true;
        self.tested = None;
        let (api, path) = (api(cx), format!("{}/test", self.path()));
        self.tasks.push(bg::spawn(
            cx,
            move || api.post(&path, body),
            move |this: &mut Self, sent, _| {
                this.testing = false;
                let sent = match sent {
                    Ok(reply) if flag(&reply, "ok") => Ok(format!("Sent. Look in {}.", channel.name())),
                    Ok(reply) => Err(Some(text(&reply, "error"))
                        .filter(|e| !e.is_empty())
                        .unwrap_or_else(|| "It didn't send.".into())),
                    Err(e) => Err(e.to_string()),
                };
                this.tested = Some((channel, sent));
            },
        ));
        cx.notify();
    }

    fn save(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(Ok(saved)) = &self.saved else { return };
        let body = match self.draft(saved, cx) {
            Ok(draft) => draft.body(),
            Err(problem) => {
                self.save_note = Some(Err(problem));
                cx.notify();
                return;
            }
        };
        self.saving = true;
        self.save_note = None;
        let (api, path) = (api(cx), self.path());
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.put(&path, body),
            |this: &mut Self, saved, window, cx| {
                this.saving = false;
                match saved {
                    Ok(config) => {
                        this.creds = config["credentials"].clone();
                        this.show(config, window, cx);
                        this.save_note = Some(Ok("Saved.".into()));
                    }
                    Err(e) => this.save_note = Some(Err(format!("Couldn't save: {e}"))),
                }
            },
        ));
        cx.notify();
    }

    fn revert(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if let Some(Ok(saved)) = self.saved.clone() {
            self.show(saved, window, cx);
        }
        self.save_note = None;
        cx.notify();
    }

    fn render_switch(&self, cx: &mut Context<Self>) -> AnyElement {
        let blocker = self.channel.and_then(|c| self.blocker(c, cx));
        let switch = Switch::new("sentinel-enabled")
            .checked(self.enabled && blocker.is_none())
            .disabled(blocker.is_some())
            .on_click(cx.listener(|this, checked: &bool, _, cx| {
                this.enabled = *checked;
                cx.notify();
            }));
        let theme = cx.theme();
        ui::card(theme)
            .justify_between()
            .child(
                v_flex()
                    .min_w_0()
                    .flex_1()
                    .gap_0p5()
                    .child(div().text_sm().font_medium().child("Turn on Sentinel"))
                    .child(
                        div()
                            .text_xs()
                            .text_color(if blocker.is_some() { theme.warning } else { theme.muted_foreground })
                            .child(blocker.unwrap_or("Watch this colony and ping you when it stalls.")),
                    ),
            )
            .child(switch)
            .into_any_element()
    }

    fn render_channel(&self, saved: &Value, cx: &mut Context<Self>) -> AnyElement {
        let picks: Vec<Button> = Channel::ALL
            .into_iter()
            .enumerate()
            .map(|(ix, channel)| {
                Button::new(("sentinel-channel", ix))
                    .small()
                    .outline()
                    .icon(channel.icon())
                    .label(channel.name())
                    .selected(self.channel == Some(channel))
                    .on_click(cx.listener(move |this, _, _, cx| this.pick(channel, cx)))
            })
            .collect();
        let body = match self.channel {
            Some(channel) => self.render_connection(channel, cx),
            None => {
                let note = if saved["channel"] == "hive" {
                    "Alerts go to the Hive inbox now, the built-in channel. Pick Telegram or Slack to get them there instead."
                } else {
                    "Pick where Sentinel pings you."
                };
                div().text_xs().text_color(cx.theme().muted_foreground).child(note).into_any_element()
            }
        };
        ui::section("Channel", cx.theme()).child(h_flex().gap_2().children(picks)).child(body).into_any_element()
    }

    fn render_connection(&self, channel: Channel, cx: &mut Context<Self>) -> AnyElement {
        let connected = self.is_connected(channel);
        let replace = (connected && !self.replacing).then(|| {
            Button::new("sentinel-replace")
                .xsmall()
                .ghost()
                .label(if channel == Channel::Slack { "Replace tokens" } else { "Replace token" })
                .on_click(cx.listener(|this, _, _, cx| {
                    this.replacing = true;
                    this.connected = None;
                    cx.notify();
                }))
        });
        let form = (!connected || self.replacing).then(|| self.render_connect(channel, connected, cx));
        let theme = cx.theme();
        let color = if connected { theme.success } else { theme.muted_foreground };
        let status = match &self.connected {
            Some((c, Ok(who))) if *c == channel && !who.is_empty() => {
                format!("Connected {} {who}", if channel == Channel::Slack { "to" } else { "as" })
            }
            _ if connected => "Connected".into(),
            _ => "Not connected".into(),
        };
        v_flex()
            .gap_2()
            .child(
                h_flex()
                    .gap_1p5()
                    .text_xs()
                    .child(ui::dot(color))
                    .child(div().text_color(color).child(status))
                    .children(replace),
            )
            .children(form)
            .into_any_element()
    }

    fn render_connect(&self, channel: Channel, connected: bool, cx: &mut Context<Self>) -> AnyElement {
        let link = channel.link();
        let copied = self.copied == Some(link);
        let copy = Button::new("sentinel-copy-link")
            .xsmall()
            .ghost()
            .icon(if copied { IconName::Check } else { IconName::Copy })
            .label(if copied { "Copied" } else { "Copy link" })
            .on_click(cx.listener(move |this, _, _, cx| {
                cx.write_to_clipboard(ClipboardItem::new_string(link.to_string()));
                this.copied = Some(link);
                cx.notify();
            }));
        let cancel = connected.then(|| {
            Button::new("sentinel-connect-cancel").small().ghost().label("Cancel").on_click(cx.listener(
                |this, _, _, cx| {
                    this.replacing = false;
                    this.connected = None;
                    cx.notify();
                },
            ))
        });
        let connect = Button::new("sentinel-connect")
            .small()
            .primary()
            .label("Connect")
            .loading(self.connecting)
            .on_click(cx.listener(move |this, _, window, cx| this.connect(channel, window, cx)));
        let error = match &self.connected {
            Some((c, Err(e))) if *c == channel => Some(e.clone()),
            _ => None,
        };
        let theme = cx.theme();
        v_flex()
            .gap_2()
            .p_3()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(div().text_sm().font_medium().child(format!("Connect {}", channel.name())))
            .child(
                h_flex()
                    .gap_2()
                    .child(div().text_xs().font_family(theme.mono_font_family.clone()).child(link))
                    .child(copy),
            )
            .child(v_flex().gap_1().children(channel.steps().iter().enumerate().map(|(ix, step)| {
                div().text_xs().text_color(theme.muted_foreground).child(format!("{}. {step}", ix + 1))
            })))
            .children(self.token_fields(channel).iter().map(|field| Input::new(field).small().mask_toggle()))
            .child(
                div().text_xs().text_color(theme.muted_foreground).child(format!(
                    "Every colony shares this {}.",
                    if channel == Channel::Slack { "app" } else { "bot" }
                )),
            )
            .when_some(error, |col, e| col.child(ui::error_line(e, theme)))
            .child(h_flex().justify_end().gap_2().children(cancel).child(connect))
            .into_any_element()
    }

    fn render_destination(&self, channel: Channel, cx: &mut Context<Self>) -> AnyElement {
        let ready = self.blocker(channel, cx).is_none();
        let detect = (channel == Channel::Telegram).then(|| {
            Button::new("sentinel-detect")
                .small()
                .outline()
                .icon(IconName::ScanSearch)
                .label("Detect")
                .tooltip("Fill in the chat that last messaged your bot")
                .loading(self.detecting)
                .disabled(!self.is_connected(channel))
                .on_click(cx.listener(|this, _, window, cx| this.detect(window, cx)))
        });
        let test = Button::new("sentinel-test")
            .small()
            .ghost()
            .icon(IconName::Send)
            .label("Send a test")
            .loading(self.testing)
            .disabled(!ready)
            .on_click(cx.listener(|this, _, _, cx| this.test(cx)));
        let tested = self.tested.as_ref().filter(|(c, _)| *c == channel).map(|(_, sent)| sent.clone());
        let detected = self.detected.clone().filter(|_| channel == Channel::Telegram);
        let theme = cx.theme();
        let hint = match channel {
            Channel::Telegram => "Send your bot any message in Telegram, then press Detect to fill in the chat.",
            Channel::Slack => {
                "Invite the bot to a channel, then paste the channel's id: the last part of its link, e.g. C0123ABC456."
            }
        };
        ui::section("Where to ping you", theme)
            .child(
                h_flex()
                    .gap_2()
                    .child(div().flex_1().min_w_0().child(Input::new(self.destination_field(channel)).small()))
                    .children(detect),
            )
            .child(div().text_xs().text_color(theme.muted_foreground).child(hint))
            .when_some(detected, |col, found| match found {
                Ok(note) => col.child(div().text_xs().text_color(theme.success).child(note)),
                Err(e) => col.child(ui::error_line(e, theme).text_xs()),
            })
            .child(h_flex().gap_2().child(test).when_some(tested, |row, sent| {
                row.child(match sent {
                    Ok(note) => div().flex_1().min_w_0().text_xs().text_color(theme.success).child(note),
                    Err(e) => ui::error_line(e, theme).flex_1().min_w_0().text_xs(),
                })
            }))
            .into_any_element()
    }

    fn render_repliers(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme();
        let hint = match self.channel {
            Some(Channel::Telegram) => {
                "Telegram user ids, one per line. Only they can answer the colony; with none, anyone in the chat can. Detect adds you."
            }
            Some(Channel::Slack) => {
                "Slack member ids (U…), one per line. Only they can answer the colony; with none, anyone in the channel can."
            }
            None => "User ids, one per line. Only they can answer the colony; with none, anyone can.",
        };
        ui::section("Who can reply", theme)
            .child(Textarea::new(&self.allowlist))
            .child(div().text_xs().text_color(theme.muted_foreground).child(hint))
            .into_any_element()
    }

    fn render_timing(&self, cx: &mut Context<Self>) -> AnyElement {
        let problem = parse_minutes(&self.minutes.read(cx).value()).err();
        let theme = cx.theme();
        ui::section("When to check", theme)
            .child(
                h_flex()
                    .gap_2()
                    .child(div().w(px(96.)).child(Input::new(&self.minutes).small()))
                    .child(div().text_sm().child("minutes idle")),
            )
            .child(match problem {
                Some(problem) => ui::error_line(problem, theme).text_xs(),
                None => div().text_xs().text_color(theme.muted_foreground).child(
                    "How long the colony may sit idle before Sentinel checks whether it's really stuck. Empty uses the default for all colonies.",
                ),
            })
            .into_any_element()
    }

    fn render_footer(&self, saved: &Value, cx: &mut Context<Self>) -> AnyElement {
        let draft = self.draft(saved, cx);
        let dirty = !draft.as_ref().is_ok_and(|d| *d == Draft::of(saved));
        let revert = dirty.then(|| {
            Button::new("sentinel-revert")
                .small()
                .ghost()
                .label("Revert")
                .on_click(cx.listener(|this, _, window, cx| this.revert(window, cx)))
        });
        let save = Button::new("sentinel-save")
            .small()
            .primary()
            .label("Save")
            .loading(self.saving)
            .disabled(!dirty || draft.is_err())
            .on_click(cx.listener(|this, _, window, cx| this.save(window, cx)));
        let theme = cx.theme();
        let note = match self.save_note.clone() {
            Some(Err(e)) => ui::error_line(e, theme),
            Some(Ok(note)) if !dirty => div().text_sm().text_color(theme.success).child(note),
            _ if dirty => div().text_xs().text_color(theme.muted_foreground).child("Not saved yet."),
            _ => div(),
        };
        h_flex()
            .gap_2()
            .pt_3()
            .border_t_1()
            .border_color(theme.border)
            .child(div().flex_1().min_w_0().child(note))
            .children(revert)
            .child(save)
            .into_any_element()
    }
}

impl Render for SentinelPanel {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let reload = Button::new("sentinel-reload")
            .xsmall()
            .ghost()
            .icon(IconName::RefreshCw)
            .tooltip("Reload, dropping unsaved changes")
            .on_click(cx.listener(|this, _, window, cx| {
                this.save_note = None;
                this.load(window, cx);
            }));
        let saved = match &self.saved {
            None => return v_flex().py_4().child(Spinner::new().small()).into_any_element(),
            Some(Err(e)) => {
                let e = format!("Couldn't load the alert settings: {e}");
                return v_flex()
                    .gap_2()
                    .py_2()
                    .child(ui::error_line(e, cx.theme()))
                    .child(h_flex().child(reload.label("Try again")))
                    .into_any_element();
            }
            Some(Ok(saved)) => saved.clone(),
        };
        let switch = self.render_switch(cx);
        let channel = self.render_channel(&saved, cx);
        let destination = self.channel.map(|c| self.render_destination(c, cx));
        let repliers = self.render_repliers(cx);
        let timing = self.render_timing(cx);
        let footer = self.render_footer(&saved, cx);
        let theme = cx.theme();
        v_flex()
            .w_full()
            .gap_5()
            .py_2()
            .child(
                h_flex()
                    .gap_2()
                    .items_start()
                    .child(Icon::new(IconName::Bell).small().text_color(theme.muted_foreground))
                    .child(div().flex_1().min_w_0().text_xs().text_color(theme.muted_foreground).child(
                        "Sentinel pings you when this colony hits a real blocker, and your reply keeps it going. Pauses that only ask \"shall I go on?\" are resumed for you.",
                    ))
                    .child(reload),
            )
            .child(switch)
            .child(channel)
            .children(destination)
            .child(repliers)
            .child(timing)
            .child(footer)
            .into_any_element()
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use serde_json::json;

    use super::{Channel, Draft, detected_note, minutes_text, missing, parse_allowlist, parse_minutes};

    #[test]
    fn parse_allowlist_takes_lines_or_commas_once_each() {
        assert_eq!(parse_allowlist("101\n 202 \r\n\n101, 303,"), vec!["101", "202", "303"]);
        assert!(parse_allowlist("  \n ").is_empty());
    }

    #[test]
    fn minutes_round_trip_through_seconds() {
        assert_eq!(minutes_text(None), "");
        assert_eq!(minutes_text(Some(300.0)), "5");
        assert_eq!(minutes_text(Some(90.0)), "1.5");
        assert_eq!(minutes_text(Some(100.0)), "1.67");
        for seconds in [60.0, 61.0, 100.0, 300.0, 3600.0] {
            assert_eq!(parse_minutes(&minutes_text(Some(seconds))), Ok(Some(seconds)));
        }
        assert_eq!(parse_minutes(" "), Ok(None));
        assert_eq!(parse_minutes("0.001"), Ok(Some(1.0)));
        assert!(parse_minutes("0").is_err());
        assert!(parse_minutes("1.2.3").is_err());
    }

    #[test]
    fn sentinel_needs_a_token_and_a_destination() {
        assert_eq!(missing(Channel::Telegram, true, "4242"), None);
        assert_eq!(missing(Channel::Telegram, true, "  "), Some("Add a chat id below first."));
        assert_eq!(missing(Channel::Slack, false, "C0AVA"), Some("Connect a Slack app below first."));
        assert!(missing(Channel::Slack, false, "").is_some());
    }

    #[test]
    fn a_draft_reads_and_writes_the_servers_shape() {
        let config = json!({
            "colony_id": "ivy_research", "sentinel_enabled": true, "channel": "telegram",
            "target": { "chat_id": "4242" }, "allowlist": ["101", 202], "thread": {},
            "classify_after_seconds": 300.0, "credentials": { "telegram": { "configured": true } },
        });
        let draft = Draft::of(&config);
        assert_eq!(draft.allowlist, vec!["101", "202"]);
        assert_eq!(Channel::Telegram.destination(&draft.target), "4242");
        assert_eq!(
            draft.body(),
            json!({
                "sentinel_enabled": true, "channel": "telegram", "target": { "chat_id": "4242" },
                "allowlist": ["101", "202"], "classify_after_seconds": 300.0,
            })
        );
        let unset = Draft::of(&json!({ "sentinel_enabled": false, "channel": "hive", "target": null }));
        assert_eq!(unset.body()["target"], json!({}));
        assert_eq!(unset.body()["classify_after_seconds"], json!(null));
        assert_eq!(Channel::Slack.target("C0AVA"), json!({ "channel": "C0AVA" }));
    }

    #[test]
    fn detected_note_names_the_chat_and_the_sender() {
        assert_eq!(
            detected_note(
                &json!({ "chat_id": "4242", "chat_title": "Mira", "sender_id": "101", "sender_name": "mira" })
            ),
            "Found Mira, and added mira to who can reply."
        );
        assert_eq!(detected_note(&json!({ "chat_id": "4242" })), "Found 4242.");
    }
}
