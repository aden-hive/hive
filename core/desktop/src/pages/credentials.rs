//! Credentials: the alert channels Sentinel pings through, the accounts the queens' tools sign in
//! with, a form to add one, and the catalog of credentials tools can use. Mirrors
//! `frontend/src/pages/credentials.tsx`, `components/AddCredentialModal.tsx` and
//! `components/SentinelConnectorsSection.tsx`.

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Map, Value, json};

use super::{flag, text};
use crate::api::{api, encode};
use crate::{bg, ui};

/// A provider id or account name as the server keeps it: lowercase, each run of anything outside
/// `[a-z0-9_-]` turned into `_`, nothing but a letter or digit first (the web form's rule), and no
/// `_` left trailing.
fn sanitize(raw: &str) -> String {
    let mut out = String::new();
    for c in raw.trim().to_lowercase().chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-' {
            out.push(c);
        } else if !out.ends_with('_') {
            out.push('_');
        }
    }
    out.trim_start_matches(|c: char| !c.is_ascii_alphanumeric()).trim_end_matches('_').to_string()
}

/// An account's identity (email, username, workspace, …) as one line.
fn identity_line(identity: &Value) -> String {
    let parts: Vec<String> = identity
        .as_object()
        .into_iter()
        .flatten()
        .filter_map(|(_, v)| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect();
    parts.join(" · ")
}

#[derive(Clone, Copy, PartialEq)]
enum Channel {
    Telegram,
    Slack,
}

impl Channel {
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

    fn blurb(self) -> &'static str {
        match self {
            Channel::Telegram => "Get pinged on Telegram when a colony stalls. Reply to keep it moving.",
            Channel::Slack => "Get pinged in Slack when a colony stalls. Reply in the thread to keep it moving.",
        }
    }

    /// Where the token is made. The page offers it to copy, as it opens no browser.
    fn link(self) -> &'static str {
        match self {
            Channel::Telegram => "https://t.me/BotFather",
            Channel::Slack => "https://api.slack.com/apps",
        }
    }

    fn steps(self) -> &'static [&'static str] {
        match self {
            Channel::Telegram => &[
                "Open @BotFather in Telegram and send /newbot.",
                "Give the bot a name, then a username that ends in \"bot\".",
                "Paste the HTTP API token it replies with below.",
            ],
            Channel::Slack => &[
                "At the Slack apps dashboard, create a new app from scratch in your workspace.",
                "Under Basic Information, make an app-level token with connections:write (xapp-…).",
                "Under OAuth & Permissions, add the chat:write bot scope.",
                "Install it to the workspace, copy the bot token (xoxb-…), and turn on Socket Mode.",
            ],
        }
    }

    fn placeholders(self) -> &'static [&'static str] {
        match self {
            Channel::Telegram => &["Bot token (123456:ABC-DEF…)"],
            Channel::Slack => &["Bot token (xoxb-…)", "App-level token (xapp-…)"],
        }
    }

    fn connected(self, status: &Value) -> bool {
        match self {
            Channel::Telegram => flag(&status["telegram"], "configured"),
            Channel::Slack => flag(&status["slack"], "bot") && flag(&status["slack"], "app"),
        }
    }
}

/// The token form of one alert channel.
struct Connect {
    channel: Channel,
    /// One field per token the channel needs, in [`Channel::placeholders`] order.
    fields: Vec<Entity<InputState>>,
    busy: bool,
    error: Option<String>,
    /// Who it connected as, once it has.
    done: Option<String>,
}

/// One key of a credential being added: its name, and its value (masked).
struct KeyRow {
    name: Entity<InputState>,
    value: Entity<InputState>,
}

pub struct CredentialsPage {
    specs: Option<Result<Value, String>>,
    sentinel: Option<Result<Value, String>>,
    connect: Option<Connect>,
    provider: Entity<InputState>,
    alias: Entity<InputState>,
    keys: Vec<KeyRow>,
    adding: bool,
    /// What the last add said: a note when it saved, a problem when it didn't.
    added: Option<Result<String, String>>,
    /// An account the user asked to remove, as (credential id, alias); a second click confirms.
    confirm_remove: Option<(String, String)>,
    /// A failed remove or sync, shown above the accounts.
    accounts_error: Option<String>,
    syncing: bool,
    search: Entity<InputState>,
    /// The spec whose instructions are open.
    opened: Option<String>,
    /// The link just copied, so its button can say so.
    copied: Option<String>,
    tasks: Vec<Task<()>>,
}

impl CredentialsPage {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let provider = cx.new(|cx| InputState::new(window, cx).placeholder("Provider, e.g. github"));
        let alias = cx.new(|cx| InputState::new(window, cx).placeholder("default"));
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search credentials"));
        for field in [&provider, &alias, &search] {
            cx.observe(field, |_, _, cx| cx.notify()).detach();
        }
        let mut page = Self {
            specs: None,
            sentinel: None,
            connect: None,
            provider,
            alias,
            keys: Vec::new(),
            adding: false,
            added: None,
            confirm_remove: None,
            accounts_error: None,
            syncing: false,
            search,
            opened: None,
            copied: None,
            tasks: Vec::new(),
        };
        page.add_key_row("api_key", window, cx);
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/credentials/specs"),
            |this: &mut Self, specs, _| this.specs = Some(specs.map_err(|e| e.to_string())),
        ));
        self.load_sentinel(cx);
    }

    fn load_sentinel(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/sentinel/credentials"),
            |this: &mut Self, status, _| this.sentinel = Some(status.map_err(|e| e.to_string())),
        ));
    }

    fn copy(&mut self, link: String, cx: &mut Context<Self>) {
        cx.write_to_clipboard(ClipboardItem::new_string(link.clone()));
        self.copied = Some(link);
        cx.notify();
    }

    fn add_key_row(&mut self, name: &str, window: &mut Window, cx: &mut Context<Self>) {
        let name_field = cx.new(|cx| InputState::new(window, cx).placeholder("field"));
        name_field.update(cx, |s, cx| s.set_value(name.to_string(), window, cx));
        let value = cx.new(|cx| InputState::new(window, cx).placeholder("value").masked(true));
        cx.observe(&value, |_, _, cx| cx.notify()).detach();
        self.keys.push(KeyRow { name: name_field, value });
        cx.notify();
    }

    fn open_connect(&mut self, channel: Channel, window: &mut Window, cx: &mut Context<Self>) {
        if self.connect.as_ref().is_some_and(|c| c.channel == channel) {
            self.connect = None;
            cx.notify();
            return;
        }
        let fields: Vec<_> = channel
            .placeholders()
            .iter()
            .map(|&p| cx.new(|cx| InputState::new(window, cx).placeholder(p).masked(true)))
            .collect();
        fields[0].update(cx, |s, cx| s.focus(window, cx));
        self.connect = Some(Connect { channel, fields, busy: false, error: None, done: None });
        cx.notify();
    }

    fn connect_channel(&mut self, cx: &mut Context<Self>) {
        let Some(connect) = self.connect.as_mut() else { return };
        let tokens: Vec<String> = connect.fields.iter().map(|f| f.read(cx).value().trim().to_string()).collect();
        if tokens.iter().any(String::is_empty) {
            connect.error = Some(if tokens.len() > 1 { "Paste both tokens." } else { "Paste the token." }.into());
            cx.notify();
            return;
        }
        connect.busy = true;
        connect.error = None;
        let channel = connect.channel;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            // Checked before saving, so a mistyped token isn't kept (the web saves first).
            move || match channel {
                Channel::Telegram => {
                    let check = api.post("/sentinel/telegram/validate", json!({ "token": tokens[0] }))?;
                    if !flag(&check, "ok") {
                        anyhow::bail!("Telegram didn't accept that token: {}", text(&check, "error"));
                    }
                    api.post(
                        "/credentials",
                        json!({ "credential_id": "telegram", "keys": { "bot_token": tokens[0] } }),
                    )?;
                    let username = text(&check, "bot_username");
                    anyhow::Ok(if username.is_empty() { text(&check, "bot_name") } else { format!("@{username}") })
                }
                Channel::Slack => {
                    let check = api.post("/sentinel/slack/validate", json!({ "token": tokens[0] }))?;
                    if !flag(&check, "ok") {
                        anyhow::bail!("Slack didn't accept the bot token: {}", text(&check, "error"));
                    }
                    api.post(
                        "/credentials",
                        json!({ "credential_id": "slack", "keys": { "access_token": tokens[0] } }),
                    )?;
                    api.post(
                        "/credentials",
                        json!({ "credential_id": "slack_app", "keys": { "access_token": tokens[1] } }),
                    )?;
                    Ok(text(&check, "team"))
                }
            },
            |this: &mut Self, connected, cx| {
                if let Some(connect) = this.connect.as_mut() {
                    connect.busy = false;
                    match connected {
                        Ok(who) => connect.done = Some(if who.is_empty() { "your bot".into() } else { who }),
                        Err(e) => connect.error = Some(e.to_string()),
                    }
                }
                this.load_sentinel(cx);
            },
        ));
        cx.notify();
    }

    fn add(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let provider = sanitize(&self.provider.read(cx).value());
        let alias =
            Some(sanitize(&self.alias.read(cx).value())).filter(|a| !a.is_empty()).unwrap_or_else(|| "default".into());
        let mut keys = Map::new();
        for row in &self.keys {
            let (name, value) =
                (row.name.read(cx).value().trim().to_string(), row.value.read(cx).value().trim().to_string());
            if !name.is_empty() && !value.is_empty() {
                keys.insert(name, Value::String(value));
            }
        }
        let problem = if provider.is_empty() {
            Some("Name the provider, e.g. github.")
        } else if keys.is_empty() {
            Some("Fill in at least one key: its name and its value.")
        } else {
            None
        };
        if let Some(problem) = problem {
            self.added = Some(Err(problem.into()));
            cx.notify();
            return;
        }
        self.adding = true;
        self.added = None;
        let api = api(cx);
        let saved_as = format!("{provider}/{alias}");
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || {
                api.post("/credentials/local", json!({ "credential_id": provider, "account": alias, "keys": keys }))
            },
            move |this: &mut Self, saved, window, cx| {
                this.adding = false;
                match saved {
                    Ok(reply) => {
                        this.added = Some(Ok(if reply["valid"] == Value::Bool(false) {
                            format!("Saved {saved_as}, but the check failed: {}", text(&reply, "message"))
                        } else {
                            format!("Saved {saved_as}.")
                        }));
                        // The secrets go; the provider and key names stay for adding another account.
                        for row in &this.keys {
                            row.value.update(cx, |s, cx| s.set_value("", window, cx));
                        }
                        this.load(cx);
                    }
                    Err(e) => this.added = Some(Err(e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn remove(&mut self, credential_id: String, alias: String, cx: &mut Context<Self>) {
        let key = (credential_id, alias);
        if self.confirm_remove.as_ref() != Some(&key) {
            self.confirm_remove = Some(key);
            cx.notify();
            return;
        }
        self.confirm_remove = None;
        self.accounts_error = None;
        let (credential_id, alias) = key;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.delete(&format!("/credentials/local/{}/{}", encode(&credential_id), encode(&alias))),
            |this: &mut Self, removed, cx| match removed {
                Ok(_) => {
                    // A "Saved …" note may be about the account just removed.
                    this.added = None;
                    this.load(cx);
                }
                Err(e) => this.accounts_error = Some(format!("Couldn't remove it: {e}")),
            },
        ));
    }

    fn sync(&mut self, cx: &mut Context<Self>) {
        self.syncing = true;
        self.accounts_error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.post("/credentials/resync", json!({})),
            |this: &mut Self, synced, cx| {
                this.syncing = false;
                match synced {
                    Ok(_) => this.load(cx),
                    Err(e) => this.accounts_error = Some(format!("Couldn't sync: {e}")),
                }
            },
        ));
        cx.notify();
    }

    fn copy_button(&self, id: impl Into<ElementId>, link: String, cx: &mut Context<Self>) -> Button {
        let copied = self.copied.as_deref() == Some(link.as_str());
        Button::new(id)
            .small()
            .ghost()
            .icon(if copied { IconName::Check } else { IconName::Copy })
            .label(if copied { "Copied" } else { "Copy link" })
            .on_click(cx.listener(move |this, _, _, cx| this.copy(link.clone(), cx)))
    }

    fn render_channels(&self, cx: &mut Context<Self>) -> AnyElement {
        let status = match &self.sentinel {
            Some(Ok(status)) => status.clone(),
            _ => Value::Null,
        };
        let mut cards = Vec::new();
        for (ix, channel) in [Channel::Telegram, Channel::Slack].into_iter().enumerate() {
            let connected = channel.connected(&status);
            let open = self.connect.as_ref().is_some_and(|c| c.channel == channel);
            let button = Button::new(("connect", ix))
                .small()
                .outline()
                .label(if open {
                    "Close"
                } else if connected {
                    "Reconnect"
                } else {
                    "Connect"
                })
                .on_click(cx.listener(move |this, _, window, cx| this.open_connect(channel, window, cx)));
            let theme = cx.theme();
            cards.push(
                v_flex()
                    .flex_1()
                    .min_w_0()
                    .gap_2()
                    .px_4()
                    .py_3()
                    .rounded_lg()
                    .border_1()
                    .border_color(if open { theme.primary } else { theme.border })
                    .bg(theme.background)
                    .child(
                        h_flex()
                            .justify_between()
                            .child(
                                h_flex()
                                    .gap_2()
                                    .child(Icon::new(channel.icon()).small())
                                    .child(div().text_sm().font_medium().child(channel.name())),
                            )
                            .child(
                                h_flex()
                                    .gap_1p5()
                                    .text_xs()
                                    .child(ui::dot(if connected { theme.success } else { theme.muted_foreground }))
                                    .child(
                                        div()
                                            .text_color(if connected { theme.success } else { theme.muted_foreground })
                                            .child(if connected { "Connected" } else { "Not connected" }),
                                    ),
                            ),
                    )
                    .child(div().text_xs().text_color(theme.muted_foreground).child(channel.blurb()))
                    .child(div().flex_1())
                    .child(h_flex().justify_end().child(button)),
            );
        }
        let form =
            self.connect.as_ref().map(|connect| self.render_connect(connect, connect.channel.connected(&status), cx));
        let theme = cx.theme().clone();
        v_flex()
            .gap_3()
            .when_some(self.sentinel.as_ref().and_then(|s| s.as_ref().err()).cloned(), |col, e| {
                col.child(ui::error_line(format!("Couldn't read the channels' status: {e}"), &theme))
            })
            .child(h_flex().gap_3().items_stretch().children(cards))
            .children(form)
            .into_any_element()
    }

    fn render_connect(&self, connect: &Connect, connected: bool, cx: &mut Context<Self>) -> AnyElement {
        let channel = connect.channel;
        let copy = self.copy_button("copy-channel-link", channel.link().to_string(), cx);
        let save = Button::new("connect-save")
            .small()
            .primary()
            .label("Connect")
            .loading(connect.busy)
            .on_click(cx.listener(|this, _, _, cx| this.connect_channel(cx)));
        let theme = cx.theme().clone();
        let mut form = v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(div().text_sm().font_semibold().child(format!("Connect {}", channel.name())));
        if let Some(who) = &connect.done {
            let joint = if channel == Channel::Slack { "to" } else { "as" };
            return form
                .child(
                    h_flex()
                        .gap_2()
                        .text_sm()
                        .child(Icon::new(IconName::CircleCheck).small().text_color(theme.success))
                        .child(format!("Connected {joint} {who}.")),
                )
                .child(ui::muted(
                    "The bot is shared by every colony. To get pinged, turn Sentinel on in a colony's Automations tab.",
                    &theme,
                ))
                .into_any_element();
        }
        if connected {
            form = form.child(
                div()
                    .text_xs()
                    .text_color(theme.success)
                    .child(format!("{} is already connected. New tokens replace the saved ones.", channel.name())),
            );
        }
        form.child(
            h_flex()
                .gap_2()
                .child(div().text_xs().font_family(theme.mono_font_family.clone()).child(channel.link()))
                .child(copy),
        )
        .child(v_flex().gap_1().children(
            channel.steps().iter().enumerate().map(|(ix, step)| {
                div().text_xs().text_color(theme.muted_foreground).child(format!("{}. {step}", ix + 1))
            }),
        ))
        .children(connect.fields.iter().map(|field| Input::new(field).small().mask_toggle()))
        .when_some(connect.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
        .child(h_flex().justify_end().child(save))
        .into_any_element()
    }

    fn render_accounts(&self, body: &Value, cx: &mut Context<Self>) -> AnyElement {
        let mut providers: Vec<(String, Vec<Value>)> = body["accounts_by_provider"]
            .as_object()
            .into_iter()
            .flatten()
            .map(|(p, accounts)| (p.clone(), accounts.as_array().cloned().unwrap_or_default()))
            .filter(|(_, a)| !a.is_empty())
            .collect();
        providers.sort_by(|a, b| a.0.cmp(&b.0));
        let sync = flag(body, "has_aden_key").then(|| {
            Button::new("sync")
                .small()
                .ghost()
                .icon(IconName::RefreshCw)
                .label("Sync from Aden")
                .loading(self.syncing)
                .on_click(cx.listener(|this, _, _, cx| this.sync(cx)))
        });
        let theme = cx.theme().clone();
        let mut groups = Vec::new();
        let mut row_ix = 0usize;
        for (provider, accounts) in providers {
            let mut group = v_flex().gap_1().child(div().text_sm().font_semibold().child(provider.clone()));
            for account in accounts {
                row_ix += 1;
                let credential_id =
                    Some(text(&account, "credential_id")).filter(|c| !c.is_empty()).unwrap_or_else(|| provider.clone());
                let alias = text(&account, "alias");
                let source = text(&account, "source");
                let who = identity_line(&account["identity"]);
                // Only accounts added on this machine can be removed here; Aden's live on its site.
                let removable = source == "local" && !alias.is_empty();
                let confirming = self.confirm_remove.as_ref().is_some_and(|(c, a)| *c == credential_id && *a == alias);
                group = group.child(
                    ui::card(&theme)
                        .justify_between()
                        .child(
                            v_flex()
                                .min_w_0()
                                .child(
                                    h_flex()
                                        .gap_2()
                                        .child(div().text_sm().font_medium().child(if alias.is_empty() {
                                            "default".to_string()
                                        } else {
                                            alias.clone()
                                        }))
                                        .child(
                                            div().text_xs().text_color(theme.muted_foreground).child(source.clone()),
                                        ),
                                )
                                .when(!who.is_empty(), |col| {
                                    col.child(div().text_xs().text_color(theme.muted_foreground).truncate().child(who))
                                }),
                        )
                        .when(removable, |row| {
                            row.child(
                                Button::new(("remove-account", row_ix))
                                    .small()
                                    .ghost()
                                    .when(confirming, |b| b.danger().label("Remove for good"))
                                    .when(!confirming, |b| b.icon(IconName::Trash).tooltip("Remove"))
                                    .on_click(cx.listener(move |this, _, _, cx| {
                                        this.remove(credential_id.clone(), alias.clone(), cx)
                                    })),
                            )
                        }),
                );
            }
            groups.push(group);
        }
        v_flex()
            .gap_3()
            .when_some(sync, |col, sync| col.child(h_flex().child(sync)))
            .when_some(self.accounts_error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .when(groups.is_empty(), |col| col.child(ui::muted("No accounts connected yet. Add one below.", &theme)))
            .children(groups)
            .into_any_element()
    }

    fn render_add(&self, cx: &mut Context<Self>) -> AnyElement {
        let can_remove = self.keys.len() > 1;
        let rows: Vec<_> = self
            .keys
            .iter()
            .enumerate()
            .map(|(ix, row)| {
                // Removed by its input, not its place: two quick clicks mustn't drop the wrong row.
                let row_id = row.name.entity_id();
                h_flex()
                    .gap_2()
                    .child(div().w(px(160.)).child(Input::new(&row.name).small()))
                    .child(div().flex_1().child(Input::new(&row.value).small().mask_toggle()))
                    .child(
                        Button::new(("remove-key", ix))
                            .small()
                            .ghost()
                            .icon(IconName::X)
                            .tooltip("Remove this key")
                            .disabled(!can_remove)
                            .on_click(cx.listener(move |this, _, _, cx| {
                                if this.keys.len() > 1 {
                                    this.keys.retain(|k| k.name.entity_id() != row_id);
                                    cx.notify();
                                }
                            })),
                    )
            })
            .collect();
        let add_row = Button::new("add-key-row")
            .small()
            .ghost()
            .icon(IconName::Plus)
            .label("Add a key")
            .on_click(cx.listener(|this, _, window, cx| this.add_key_row("", window, cx)));
        let save = Button::new("save-credential")
            .small()
            .primary()
            .label("Save")
            .loading(self.adding)
            .on_click(cx.listener(|this, _, window, cx| this.add(window, cx)));
        let theme = cx.theme().clone();
        // Show what an id will be saved as when the typed one isn't already in the server's form.
        let typed = [self.provider.read(cx).value().to_string(), self.alias.read(cx).value().to_string()];
        let hint = typed.iter().any(|t| !t.is_empty() && sanitize(t) != *t).then(|| {
            format!(
                "Saved as {}/{}",
                sanitize(&typed[0]),
                Some(sanitize(&typed[1])).filter(|a| !a.is_empty()).unwrap_or_else(|| "default".into())
            )
        });
        v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .child(
                h_flex()
                    .gap_2()
                    .child(div().flex_1().child(Input::new(&self.provider).small()))
                    .child(div().w(px(220.)).child(Input::new(&self.alias).small())),
            )
            .child(div().text_xs().text_color(theme.muted_foreground).child(hint.unwrap_or_else(|| {
                "The account name tells several accounts of one provider apart, e.g. work and personal.".into()
            })))
            .child(v_flex().gap_2().children(rows))
            .when_some(self.added.clone(), |col, added| match added {
                Ok(note) if note.contains("the check failed") => {
                    col.child(div().text_sm().text_color(theme.warning).child(note))
                }
                Ok(note) => col.child(div().text_sm().text_color(theme.success).child(note)),
                Err(e) => col.child(ui::error_line(e, &theme)),
            })
            .child(h_flex().justify_between().child(add_row).child(save))
            .into_any_element()
    }

    fn render_specs(&self, body: &Value, cx: &mut Context<Self>) -> AnyElement {
        let query = self.search.read(cx).value().to_lowercase();
        let mut specs: Vec<Value> = body["specs"].as_array().cloned().unwrap_or_default();
        let total = specs.len();
        let available = specs.iter().filter(|s| flag(s, "available")).count();
        specs.retain(|s| {
            query.is_empty()
                || ["credential_name", "credential_id", "env_var", "description"]
                    .iter()
                    .any(|k| text(s, k).to_lowercase().contains(&query))
                || s["tools"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(Value::as_str)
                    .any(|t| t.to_lowercase().contains(&query))
        });
        specs.sort_by_key(|s| (!flag(s, "available"), text(s, "credential_name").to_lowercase()));

        let mut rows = Vec::new();
        for (ix, spec) in specs.iter().enumerate() {
            let id = text(spec, "credential_id");
            let is_open = self.opened.as_deref() == Some(id.as_str());
            let help = text(spec, "help_url");
            let copy = (is_open && !help.is_empty()).then(|| self.copy_button(("copy-help", ix), help.clone(), cx));
            let toggle = cx.listener({
                let id = id.clone();
                move |this, _: &ClickEvent, _, cx| {
                    this.opened = if this.opened.as_deref() == Some(id.as_str()) { None } else { Some(id.clone()) };
                    cx.notify();
                }
            });
            let theme = cx.theme();
            let ready = flag(spec, "available");
            let env_var = text(spec, "env_var");
            let tools: Vec<&str> = spec["tools"].as_array().into_iter().flatten().filter_map(Value::as_str).collect();
            let mut row = v_flex()
                .gap_2()
                .px_4()
                .py_3()
                .rounded_lg()
                .border_1()
                .border_color(theme.border)
                .bg(theme.background)
                .child(
                    h_flex()
                        .id(("spec", ix))
                        .gap_3()
                        .cursor_pointer()
                        .child(ui::dot(if ready { theme.success } else { theme.muted_foreground }))
                        .child(
                            v_flex()
                                .min_w_0()
                                .flex_1()
                                .child(
                                    h_flex()
                                        .gap_2()
                                        .child(div().text_sm().font_medium().child(text(spec, "credential_name")))
                                        .when(!env_var.is_empty(), |row| {
                                            row.child(
                                                div()
                                                    .text_xs()
                                                    .font_family(theme.mono_font_family.clone())
                                                    .text_color(theme.muted_foreground)
                                                    .child(env_var.clone()),
                                            )
                                        }),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .text_color(theme.muted_foreground)
                                        .truncate()
                                        .child(text(spec, "description")),
                                ),
                        )
                        .child(
                            div()
                                .text_xs()
                                .text_color(if ready { theme.success } else { theme.muted_foreground })
                                .child(if ready { "Available" } else { "Not set" }),
                        )
                        .child(
                            Icon::new(if is_open { IconName::ChevronDown } else { IconName::ChevronRight })
                                .small()
                                .text_color(theme.muted_foreground),
                        )
                        .on_click(toggle),
                );
            if is_open {
                let instructions = text(spec, "api_key_instructions");
                row = row.child(
                    v_flex()
                        .gap_2()
                        .pl_5()
                        .pt_1()
                        .border_t_1()
                        .border_color(theme.border)
                        .when(!instructions.is_empty(), |col| {
                            col.child(
                                v_flex()
                                    .gap_0p5()
                                    .text_sm()
                                    .children(instructions.lines().map(|line| div().child(line.to_string()))),
                            )
                        })
                        .when_some(copy, |col, copy| {
                            col.child(
                                h_flex()
                                    .gap_2()
                                    .child(
                                        div()
                                            .text_xs()
                                            .font_family(theme.mono_font_family.clone())
                                            .text_color(theme.muted_foreground)
                                            .child(help.clone()),
                                    )
                                    .child(copy),
                            )
                        })
                        .when(!tools.is_empty(), |col| {
                            col.child(
                                div()
                                    .text_xs()
                                    .text_color(theme.muted_foreground)
                                    .child(format!("Used by {}", ui::clip(&tools.join(", "), 300))),
                            )
                        })
                        .child(div().text_xs().text_color(theme.muted_foreground).child(format!("Id: {id}"))),
                );
            }
            rows.push(row);
        }
        let theme = cx.theme().clone();
        v_flex()
            .gap_2()
            .child(
                h_flex()
                    .gap_3()
                    .child(div().w(px(320.)).child(Input::new(&self.search).small()))
                    .child(ui::muted(format!("{available} of {total} available"), &theme)),
            )
            .when(rows.is_empty(), |col| col.child(ui::muted("Nothing matches that search.", &theme)))
            .children(rows)
            .into_any_element()
    }
}

impl Render for CredentialsPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) = ui::page(
            "credentials-body",
            "Credentials",
            "The keys and accounts the queens' tools sign in with, and where Sentinel pings you.",
            &theme,
        );
        let header = header.child(
            h_flex().pt_2().child(
                Button::new("refresh")
                    .small()
                    .ghost()
                    .icon(IconName::RefreshCw)
                    .label("Refresh")
                    .on_click(cx.listener(|this, _, _, cx| this.load(cx))),
            ),
        );
        let channels = self.render_channels(cx);
        let content = match self.specs.clone() {
            None => v_flex().p_8().child(Spinner::new()),
            Some(Err(e)) => v_flex()
                .gap_8()
                .px_8()
                .py_6()
                .w_full()
                .max_w(px(880.))
                .mx_auto()
                .child(ui::section("Alert channels", &theme).child(channels))
                .child(ui::error_line(format!("Couldn't load credentials: {e}"), &theme)),
            Some(Ok(specs)) => v_flex()
                .gap_8()
                .px_8()
                .py_6()
                .w_full()
                .max_w(px(880.))
                .mx_auto()
                .child(ui::section("Alert channels", &theme).child(channels))
                .child(ui::section("Connected accounts", &theme).child(self.render_accounts(&specs, cx)))
                .child(ui::section("Add a credential", &theme).child(self.render_add(cx)))
                .child(ui::section("What tools can use", &theme).child(self.render_specs(&specs, cx))),
        };
        v_flex().size_full().child(header).child(body.child(content))
    }
}

#[cfg(test)]
mod tests {
    use super::sanitize;

    #[test]
    fn sanitize_keeps_the_servers_id_form() {
        assert_eq!(sanitize("GitHub"), "github");
        assert_eq!(sanitize("  Mira Work  "), "mira_work");
        assert_eq!(sanitize("__ivy-2"), "ivy-2");
        assert_eq!(sanitize("a/b\\c d"), "a_b_c_d");
        assert_eq!(sanitize("zed!!"), "zed");
        assert_eq!(sanitize("!!!"), "");
    }
}
