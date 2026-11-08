//! Which tools each queen and colony may use, and the MCP servers the tools come from.
//! Mirrors `frontend/src/pages/tool-library.tsx`, `components/ToolsEditor.tsx` and
//! `components/McpServersPanel.tsx`.

use std::collections::{BTreeSet, HashMap, HashSet};

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::checkbox::Checkbox;
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};
use gpui_kit::component::menu::{DropdownMenu as _, PopupMenuItem};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::{flag, text};
use crate::api::{Api, Queen, api, encode};
use crate::{bg, ui};

#[derive(Clone, Copy, PartialEq)]
enum Tab {
    Queens,
    Colonies,
    Mcp,
}

/// Whose allowlist an editor holds.
#[derive(Clone, PartialEq)]
enum Subject {
    Queen(String),
    Colony(String),
}

impl Subject {
    fn path(&self) -> String {
        match self {
            Subject::Queen(id) => format!("/queen/{}/tools", encode(id)),
            Subject::Colony(name) => format!("/colony/{}/tools", encode(name)),
        }
    }
}

/// A queen's or colony's tool allowlist, as saved and as being edited.
struct Editor {
    subject: Subject,
    snapshot: Option<Result<Value, String>>,
    /// The saved allowlist; `None` allows every tool.
    baseline: Option<BTreeSet<String>>,
    draft: Option<BTreeSet<String>>,
    expanded: HashSet<String>,
    saving: bool,
    saved: bool,
    confirm_reset: bool,
    error: Option<String>,
}

impl Editor {
    fn new(subject: Subject) -> Self {
        Self {
            subject,
            snapshot: None,
            baseline: None,
            draft: None,
            expanded: HashSet::new(),
            saving: false,
            saved: false,
            confirm_reset: false,
            error: None,
        }
    }

    /// Take a fresh snapshot as the saved state, dropping any edits.
    fn apply(&mut self, snapshot: Value) {
        self.baseline = allowlist(&snapshot);
        self.draft = self.baseline.clone();
        self.snapshot = Some(Ok(snapshot));
    }
}

/// Tools shown together: a category, else the MCP server they come from.
struct Group {
    key: String,
    title: String,
    /// (name, description)
    tools: Vec<(String, String)>,
    /// Always-enabled categories bypass the allowlist, so they can't be turned off.
    locked: bool,
}

struct AddForm {
    name: Entity<InputState>,
    transport: &'static str,
    command: Entity<InputState>,
    args: Entity<TextareaState>,
    env: Entity<TextareaState>,
    cwd: Entity<InputState>,
    url: Entity<InputState>,
    headers: Entity<TextareaState>,
    socket: Entity<InputState>,
    description: Entity<InputState>,
    mode: &'static str,
    submitting: bool,
    error: Option<String>,
}

pub struct ToolsPage {
    tab: Tab,
    queens: Option<Result<Vec<Queen>, String>>,
    colonies: Option<Result<Vec<Value>, String>>,
    queen_editor: Option<Editor>,
    colony_editor: Option<Editor>,
    servers: Option<Result<Vec<Value>, String>>,
    /// Servers with a write in flight.
    busy: HashSet<String>,
    /// A server the user asked to remove; a second click confirms.
    confirm_remove: Option<String>,
    mcp_error: Option<String>,
    add: Option<AddForm>,
    tasks: Vec<Task<()>>,
}

/// Plain names for the backend's category ids; others are Title Cased. Kept in step with the web's list.
const CATEGORY_LABELS: [(&str, &str); 26] = [
    ("file_ops", "Files & documents"),
    ("code_editing", "Read & edit code"),
    ("files_core", "Files & documents"),
    ("terminal_basic", "Terminal & commands"),
    ("terminal_core", "Terminal & commands"),
    ("terminal_advanced", "Terminal (advanced)"),
    ("terminal_extended", "Terminal (advanced)"),
    ("context_awareness", "Time, account & memory"),
    ("context_core", "Time & account info"),
    ("browser_core", "Web browsing & automation"),
    ("web_core", "Web research"),
    ("research", "Web research"),
    ("security", "Security scanning"),
    ("charts", "Charts & diagrams"),
    ("media", "Image generation"),
    ("spreadsheet_advanced", "Spreadsheets & data"),
    ("email_oauth", "Email"),
    ("email_senders", "Campaign email"),
    ("calendar_oauth", "Calendar"),
    ("google_workspace", "Google Docs & Sheets"),
    ("github_oauth", "GitHub"),
    ("hubspot_oauth", "CRM (HubSpot)"),
    ("notion_oauth", "Notion"),
    ("slack_oauth", "Slack"),
    ("browser_basic", "Web browsing & automation"),
    ("browser_interaction", "Web browsing & automation"),
];

/// "web_core" or "chart-tools" → "Web Core", "Chart Tools".
fn title_case(id: &str) -> String {
    id.split(['_', '-'])
        .filter(|w| !w.is_empty())
        .map(|w| {
            let mut chars = w.chars();
            chars.next().map(|c| c.to_uppercase().chain(chars).collect::<String>()).unwrap_or_default()
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn category_label(id: &str) -> String {
    CATEGORY_LABELS.iter().find(|(k, _)| *k == id).map(|(_, v)| v.to_string()).unwrap_or_else(|| title_case(id))
}

fn allowlist(snapshot: &Value) -> Option<BTreeSet<String>> {
    snapshot["enabled_mcp_tools"]
        .as_array()
        .map(|names| names.iter().filter_map(|n| n.as_str().map(str::to_string)).collect())
}

/// Group the snapshot's tools: by category first (a tool in several lands in the first), then by
/// server. Tools tied to a provider are left out, as the web does while its provider list is empty.
fn groups(snapshot: &Value) -> Vec<Group> {
    let categories = snapshot["categories"].as_array().cloned().unwrap_or_default();
    let mut category_of: HashMap<String, String> = HashMap::new();
    let mut groups: Vec<Group> = Vec::new();
    for category in &categories {
        let name = text(category, "name");
        for tool in category["tools"].as_array().into_iter().flatten().filter_map(Value::as_str) {
            category_of.entry(tool.to_string()).or_insert_with(|| name.clone());
        }
        groups.push(Group {
            key: format!("cat:{name}"),
            title: category_label(&name),
            tools: Vec::new(),
            locked: flag(category, "always_enabled"),
        });
    }
    for server in snapshot["mcp_servers"].as_array().into_iter().flatten() {
        let server_name = text(server, "name");
        for tool in server["tools"].as_array().into_iter().flatten().filter(|t| text(t, "provider").is_empty()) {
            let name = text(tool, "name");
            let (key, title) = match category_of.get(&name) {
                Some(category) => (format!("cat:{category}"), category_label(category)),
                None if !server_name.is_empty() && server_name != "(unknown)" => {
                    (format!("srv:{server_name}"), title_case(&server_name))
                }
                None => ("other".to_string(), "Other tools".to_string()),
            };
            let at = match groups.iter().position(|g| g.key == key) {
                Some(at) => at,
                None => {
                    groups.push(Group { key, title, tools: Vec::new(), locked: false });
                    groups.len() - 1
                }
            };
            groups[at].tools.push((name, text(tool, "description")));
        }
    }
    groups.retain(|g| !g.tools.is_empty());
    groups
}

/// The MCP name as the server takes it: lowercase letters, digits, `-` and `_`.
fn sanitize_name(name: &str) -> String {
    name.to_lowercase()
        .chars()
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '-' || *c == '_')
        .collect()
}

/// `KEY=VALUE` lines as a JSON object; lines without `=` or a key are skipped.
fn key_values(lines: &str) -> serde_json::Map<String, Value> {
    lines
        .lines()
        .filter_map(|line| {
            let (key, value) = line.trim().split_once('=')?;
            let key = key.trim();
            (!key.is_empty()).then(|| (key.to_string(), Value::String(value.trim().to_string())))
        })
        .collect()
}

impl ToolsPage {
    pub fn new(_: &mut Window, cx: &mut Context<Self>) -> Self {
        let mut page = Self {
            tab: Tab::Queens,
            queens: None,
            colonies: None,
            queen_editor: None,
            colony_editor: None,
            servers: None,
            busy: HashSet::new(),
            confirm_remove: None,
            mcp_error: None,
            add: None,
            tasks: Vec::new(),
        };
        page.load_subjects(cx);
        page.load_servers(cx);
        page
    }

    /// The queens and colonies, opening the first of each once known.
    fn load_subjects(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let queens = api.queens().map_err(|e| e.to_string());
                let colonies = api.get("/colonies/tools-index").map_err(|e| e.to_string()).map(|v| {
                    let mut colonies = v["colonies"].as_array().cloned().unwrap_or_default();
                    colonies.sort_by_key(|c| text(c, "name"));
                    colonies
                });
                anyhow::Ok((queens, colonies))
            },
            |this: &mut Self, loaded, cx| {
                let Ok((queens, colonies)) = loaded else { return };
                if this.queen_editor.is_none()
                    && let Ok(Some(first)) = queens.as_ref().map(|q| q.first())
                {
                    this.open(Subject::Queen(first.id.clone()), cx);
                }
                if this.colony_editor.is_none()
                    && let Ok(Some(first)) = colonies.as_ref().map(|c| c.first())
                {
                    this.open(Subject::Colony(text(first, "name")), cx);
                }
                this.queens = Some(queens);
                this.colonies = Some(colonies);
            },
        ));
    }

    fn editor(&mut self, subject: &Subject) -> Option<&mut Editor> {
        match subject {
            Subject::Queen(_) => self.queen_editor.as_mut(),
            Subject::Colony(_) => self.colony_editor.as_mut(),
        }
        .filter(|e| e.subject == *subject)
    }

    /// The editor the open tab shows.
    fn current(&mut self) -> Option<&mut Editor> {
        match self.tab {
            Tab::Queens => self.queen_editor.as_mut(),
            Tab::Colonies => self.colony_editor.as_mut(),
            Tab::Mcp => None,
        }
    }

    fn open(&mut self, subject: Subject, cx: &mut Context<Self>) {
        let editor = Editor::new(subject.clone());
        match subject {
            Subject::Queen(_) => self.queen_editor = Some(editor),
            Subject::Colony(_) => self.colony_editor = Some(editor),
        }
        let api = api(cx);
        let path = subject.path();
        self.tasks.push(bg::spawn(
            cx,
            move || api.get(&path),
            move |this: &mut Self, loaded, _| {
                let Some(editor) = this.editor(&subject) else { return };
                match loaded {
                    Ok(snapshot) => editor.apply(snapshot),
                    Err(e) => editor.snapshot = Some(Err(e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn set_tools(&mut self, names: Vec<String>, on: bool, cx: &mut Context<Self>) {
        let Some(editor) = self.current() else { return };
        let Some(Ok(snapshot)) = &editor.snapshot else { return };
        // Turning one off from "every tool" starts from the full visible list.
        let mut draft = editor.draft.clone().unwrap_or_else(|| {
            groups(snapshot).into_iter().flat_map(|g| g.tools.into_iter().map(|(n, _)| n)).collect()
        });
        for name in names {
            if on {
                draft.insert(name);
            } else {
                draft.remove(&name);
            }
        }
        editor.draft = Some(draft);
        editor.saved = false;
        cx.notify();
    }

    /// Write the allowlist (or drop it, for `reset`), then take the subject's fresh snapshot.
    fn save(&mut self, reset: bool, cx: &mut Context<Self>) {
        let Some(editor) = self.current() else { return };
        let Some(Ok(snapshot)) = &editor.snapshot else { return };
        // Only the tools the server lists go out; the saved list can hold names it no longer has.
        let known: HashSet<String> =
            groups(snapshot).into_iter().flat_map(|g| g.tools.into_iter().map(|(n, _)| n)).collect();
        let payload = match &editor.draft {
            None => Value::Null,
            Some(draft) => json!(draft.iter().filter(|n| known.contains(*n)).collect::<Vec<_>>()),
        };
        let subject = editor.subject.clone();
        editor.saving = true;
        editor.confirm_reset = false;
        editor.error = None;
        let api = api(cx);
        let path = subject.path();
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let result =
                    if reset { api.delete(&path)? } else { api.patch(&path, json!({ "enabled_mcp_tools": payload }))? };
                // Queens answer with the whole snapshot; colonies may not.
                if result["mcp_servers"].is_array() { Ok(result) } else { api.get(&path) }
            },
            move |this: &mut Self, done, _| {
                let Some(editor) = this.editor(&subject) else { return };
                editor.saving = false;
                match done {
                    Ok(snapshot) => {
                        editor.apply(snapshot);
                        editor.saved = true;
                    }
                    Err(e) => editor.error = Some(e.to_string()),
                }
            },
        ));
        cx.notify();
    }

    fn load_servers(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/mcp/servers"),
            |this: &mut Self, loaded, _| {
                this.servers = Some(
                    loaded.map(|v| v["servers"].as_array().cloned().unwrap_or_default()).map_err(|e| e.to_string()),
                )
            },
        ));
    }

    /// Run a write on one server, then reload the list; a failure shows above it.
    fn server_write(
        &mut self,
        name: String,
        work: impl FnOnce(Api) -> anyhow::Result<Value> + Send + 'static,
        cx: &mut Context<Self>,
    ) {
        self.busy.insert(name.clone());
        self.mcp_error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || work(api),
            move |this: &mut Self, done, cx| {
                this.busy.remove(&name);
                this.confirm_remove = None;
                if let Err(e) = done {
                    this.mcp_error = Some(format!("{name}: {e}"));
                }
                this.load_servers(cx);
            },
        ));
        cx.notify();
    }

    fn toggle_add(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.add.take().is_none() {
            let input = |placeholder: &'static str, window: &mut Window, cx: &mut Context<Self>| {
                let state = cx.new(|cx| InputState::new(window, cx).placeholder(placeholder));
                cx.observe(&state, |_, _, cx| cx.notify()).detach();
                state
            };
            let lines = |placeholder: &'static str, window: &mut Window, cx: &mut Context<Self>| {
                cx.new(|cx| TextareaState::new(window, cx).auto_grow(2, 8).placeholder(placeholder))
            };
            let form = AddForm {
                name: input("my-search-tool", window, cx),
                transport: "stdio",
                command: input("uv", window, cx),
                args: lines("run\npython\nmy_server.py", window, cx),
                env: lines("API_KEY=…", window, cx),
                cwd: input("/path/to/repo", window, cx),
                url: input("https://example.com/mcp", window, cx),
                headers: lines("Authorization=Bearer …", window, cx),
                socket: input("/tmp/mcp.sock", window, cx),
                description: input("What this server does", window, cx),
                mode: "tools",
                submitting: false,
                error: None,
            };
            form.name.update(cx, |s, cx| s.focus(window, cx));
            self.add = Some(form);
        }
        cx.notify();
    }

    /// The add request's body, or why it can't be sent yet.
    fn add_body(form: &AddForm, cx: &App) -> Result<Value, &'static str> {
        let value = |s: &Entity<InputState>| s.read(cx).value().trim().to_string();
        let name = sanitize_name(&value(&form.name));
        if name.is_empty() {
            return Err("Give the server a name.");
        }
        let mut body = json!({ "name": name, "transport": form.transport, "mode": if form.transport == "unix" { "tools" } else { form.mode } });
        let description = value(&form.description);
        if !description.is_empty() {
            body["description"] = json!(description);
        }
        match form.transport {
            "stdio" => {
                let command = value(&form.command);
                if command.is_empty() {
                    return Err("A stdio server needs a command.");
                }
                body["command"] = json!(command);
                let args: Vec<String> = form
                    .args
                    .read(cx)
                    .value()
                    .lines()
                    .map(str::trim)
                    .filter(|l| !l.is_empty())
                    .map(str::to_string)
                    .collect();
                if !args.is_empty() {
                    body["args"] = json!(args);
                }
                let env = key_values(&form.env.read(cx).value());
                if !env.is_empty() {
                    body["env"] = Value::Object(env);
                }
                let cwd = value(&form.cwd);
                if !cwd.is_empty() {
                    body["cwd"] = json!(cwd);
                }
            }
            "unix" => {
                let socket = value(&form.socket);
                if socket.is_empty() {
                    return Err("A unix server needs a socket path.");
                }
                body["socket_path"] = json!(socket);
            }
            _ => {
                let url = value(&form.url);
                if url.is_empty() {
                    return Err("An http or sse server needs a URL.");
                }
                body["url"] = json!(url);
                let headers = key_values(&form.headers.read(cx).value());
                if !headers.is_empty() {
                    body["headers"] = Value::Object(headers);
                }
            }
        }
        Ok(body)
    }

    fn submit_add(&mut self, cx: &mut Context<Self>) {
        let Some(form) = self.add.as_ref() else { return };
        let body = match Self::add_body(form, cx) {
            Ok(body) => body,
            Err(problem) => {
                if let Some(form) = self.add.as_mut() {
                    form.error = Some(problem.into());
                }
                cx.notify();
                return;
            }
        };
        let Some(form) = self.add.as_mut() else { return };
        form.submitting = true;
        form.error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let added = api.post("/mcp/servers", body)?;
                // The check fills in the tool count; a failing one still leaves the server added.
                let name = text(&added["server"], "name");
                api.post(&format!("/mcp/servers/{}/health", encode(&name)), json!({})).ok();
                Ok(added)
            },
            |this: &mut Self, done, cx| match done {
                Ok(_) => {
                    this.add = None;
                    this.load_servers(cx);
                }
                Err(e) => {
                    if let Some(form) = this.add.as_mut() {
                        form.submitting = false;
                        form.error = Some(e.to_string());
                    }
                }
            },
        ));
        cx.notify();
    }

    fn render_picker(&self, cx: &mut Context<Self>) -> AnyElement {
        let page = cx.entity().downgrade();
        let (items, current, label): (Vec<(Subject, String)>, Option<Subject>, String) = match self.tab {
            Tab::Queens => {
                let queens = match &self.queens {
                    Some(Ok(queens)) => queens.clone(),
                    _ => Vec::new(),
                };
                let items: Vec<(Subject, String)> =
                    queens.iter().map(|q| (Subject::Queen(q.id.clone()), queen_label(q))).collect();
                let current = self.queen_editor.as_ref().map(|e| e.subject.clone());
                let label = items
                    .iter()
                    .find(|(s, _)| Some(s) == current.as_ref())
                    .map(|(_, l)| l.clone())
                    .unwrap_or_else(|| "Choose a queen".into());
                (items, current, label)
            }
            _ => {
                let colonies = match &self.colonies {
                    Some(Ok(colonies)) => colonies.clone(),
                    _ => Vec::new(),
                };
                let items: Vec<(Subject, String)> = colonies
                    .iter()
                    .map(|c| {
                        let owner = text(c, "queen_name");
                        (
                            Subject::Colony(text(c, "name")),
                            if owner.is_empty() { text(c, "name") } else { format!("{} · @{owner}", text(c, "name")) },
                        )
                    })
                    .collect();
                let current = self.colony_editor.as_ref().map(|e| e.subject.clone());
                let label = items
                    .iter()
                    .find(|(s, _)| Some(s) == current.as_ref())
                    .map(|(_, l)| l.clone())
                    .unwrap_or_else(|| "Choose a colony".into());
                (items, current, label)
            }
        };
        Button::new("subject-picker")
            .small()
            .outline()
            .label(label)
            .dropdown_caret(true)
            .dropdown_menu(move |mut menu, _, _| {
                for (subject, label) in &items {
                    let page = page.clone();
                    let pick = subject.clone();
                    menu = menu.item(
                        PopupMenuItem::new(label.clone()).checked(current.as_ref() == Some(subject)).on_click(
                            move |_, _, cx| {
                                page.update(cx, |this, cx| this.open(pick.clone(), cx)).ok();
                            },
                        ),
                    );
                }
                menu.max_h(px(420.)).scrollable(true)
            })
            .into_any_element()
    }

    fn render_group(
        &self,
        group: &Group,
        draft: &Option<BTreeSet<String>>,
        expanded: bool,
        ix: usize,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let theme = cx.theme().clone();
        let names: Vec<String> = group.tools.iter().map(|(n, _)| n.clone()).collect();
        let allowed = |name: &str| draft.as_ref().is_none_or(|d| d.contains(name));
        let on = names.iter().filter(|n| allowed(n)).count();
        let key = group.key.clone();
        let header = h_flex()
            .gap_2()
            .px_3()
            .py_2()
            .child(if group.locked {
                Icon::new(IconName::Lock).xsmall().text_color(theme.muted_foreground).into_any_element()
            } else {
                let names = names.clone();
                Checkbox::new(("group-check", ix))
                    .checked(on == names.len())
                    .on_click(cx.listener(move |this, _: &bool, _, cx| {
                        // A partly-on group turns fully on first, as a click on its checkbox does on the web.
                        let all_on = this
                            .current()
                            .and_then(|e| e.draft.clone())
                            .is_none_or(|d| names.iter().all(|n| d.contains(n)));
                        this.set_tools(names.clone(), !all_on, cx);
                    }))
                    .into_any_element()
            })
            .child(
                h_flex()
                    .id(("group", ix))
                    .flex_1()
                    .gap_2()
                    .cursor_pointer()
                    .child(
                        Icon::new(if expanded { IconName::ChevronDown } else { IconName::ChevronRight })
                            .xsmall()
                            .text_color(theme.muted_foreground),
                    )
                    .child(div().flex_1().text_sm().font_medium().child(group.title.clone()))
                    .child(div().text_xs().text_color(theme.muted_foreground).child(if group.locked {
                        group.tools.len().to_string()
                    } else {
                        format!("{on}/{}", group.tools.len())
                    }))
                    .on_click(cx.listener(move |this, _, _, cx| {
                        if let Some(editor) = this.current()
                            && !editor.expanded.remove(&key)
                        {
                            editor.expanded.insert(key.clone());
                        }
                        cx.notify();
                    })),
            );
        let mut card = v_flex().rounded_lg().border_1().border_color(theme.border).bg(theme.background).child(header);
        if expanded {
            let rows = group.tools.iter().map(|(name, description)| {
                let mark = if group.locked {
                    Icon::new(IconName::Lock).xsmall().text_color(theme.muted_foreground).into_any_element()
                } else {
                    let tool = name.clone();
                    Checkbox::new(SharedString::from(format!("tool:{}:{name}", group.key)))
                        .checked(allowed(name))
                        .on_click(cx.listener(move |this, checked: &bool, _, cx| {
                            this.set_tools(vec![tool.clone()], *checked, cx)
                        }))
                        .into_any_element()
                };
                h_flex().gap_2().items_start().px_3().py_1().child(div().pt_0p5().child(mark)).child(
                    v_flex()
                        .min_w_0()
                        .child(div().text_sm().font_family(theme.mono_font_family.clone()).child(name.clone()))
                        .when(!description.is_empty(), |col| {
                            col.child(
                                div().text_xs().text_color(theme.muted_foreground).child(ui::clip(description, 220)),
                            )
                        }),
                )
            });
            card = card.child(v_flex().py_1().border_t_1().border_color(theme.border).children(rows));
        }
        card.into_any_element()
    }

    fn render_editor(&self, editor: &Editor, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let snapshot = match &editor.snapshot {
            None => return Spinner::new().into_any_element(),
            Some(Err(e)) => return ui::error_line(format!("Couldn't load tools: {e}"), &theme).into_any_element(),
            Some(Ok(snapshot)) => snapshot,
        };
        let is_queen = matches!(editor.subject, Subject::Queen(_));
        let groups = groups(snapshot);
        let draft = &editor.draft;
        let lifecycle = snapshot["lifecycle"].as_array().cloned().unwrap_or_default();
        let synthetic = snapshot["synthetic"].as_array().cloned().unwrap_or_default();
        let system_count = lifecycle.len() + synthetic.len();
        let locked_count: usize = groups.iter().filter(|g| g.locked).map(|g| g.tools.len()).sum();
        let searchable_total: usize = groups.iter().filter(|g| !g.locked).map(|g| g.tools.len()).sum();
        let searchable_on: usize = groups
            .iter()
            .filter(|g| !g.locked)
            .flat_map(|g| g.tools.iter())
            .filter(|(n, _)| draft.as_ref().is_none_or(|d| d.contains(n)))
            .count();
        let dirty = editor.draft != editor.baseline;

        let tier = |title: &str, count: String, blurb: &str| {
            v_flex()
                .gap_0p5()
                .pt_2()
                .child(
                    h_flex()
                        .gap_2()
                        .child(div().text_xs().font_semibold().child(title.to_uppercase()))
                        .child(div().text_xs().text_color(theme.muted_foreground).child(count)),
                )
                .child(ui::muted(blurb.to_string(), &theme).text_xs())
        };

        // The lifecycle and synthetic tools sit in a group of their own, locked like the always-on categories.
        let system = Group {
            key: "system".into(),
            title: "System & control".into(),
            tools: synthetic
                .iter()
                .chain(lifecycle.iter())
                .map(|t| (text(t, "name"), text(t, "description")))
                .collect(),
            locked: true,
        };
        let mut locked_groups = Vec::new();
        if !system.tools.is_empty() {
            locked_groups.push(self.render_group(&system, draft, editor.expanded.contains(&system.key), 0, cx));
        }
        let mut open_groups = Vec::new();
        for (ix, group) in groups.iter().enumerate() {
            let element = self.render_group(group, draft, editor.expanded.contains(&group.key), ix + 1, cx);
            if group.locked { locked_groups.push(element) } else { open_groups.push(element) }
        }

        let is_role_default = flag(snapshot, "is_role_default");
        let actions = h_flex()
            .gap_2()
            .pt_2()
            .child(
                Button::new("save-tools")
                    .small()
                    .primary()
                    .icon(IconName::Check)
                    .label("Save")
                    .loading(editor.saving)
                    .disabled(!dirty)
                    .on_click(cx.listener(|this, _, _, cx| this.save(false, cx))),
            )
            .child(
                Button::new("cancel-tools")
                    .small()
                    .outline()
                    .label("Cancel")
                    .disabled(!dirty || editor.saving)
                    .on_click(cx.listener(|this, _, _, cx| {
                        if let Some(editor) = this.current() {
                            editor.draft = editor.baseline.clone();
                            editor.error = None;
                        }
                        cx.notify();
                    })),
            )
            .when(editor.saved && !dirty, |row| row.child(div().text_xs().text_color(theme.success).child("Saved")))
            .when(dirty && !editor.saving, |row| {
                row.child(div().text_xs().text_color(theme.warning).child("Unsaved changes"))
            })
            .child(div().flex_1())
            .child(
                Button::new("allow-all")
                    .small()
                    .ghost()
                    .label("Allow all")
                    .disabled(editor.saving || draft.is_none())
                    .on_click(cx.listener(|this, _, _, cx| {
                        if let Some(editor) = this.current() {
                            editor.draft = None;
                            editor.saved = false;
                        }
                        cx.notify();
                    })),
            )
            .when(is_queen, |row| {
                row.child(
                    Button::new("reset-tools")
                        .small()
                        .ghost()
                        .disabled(editor.saving || is_role_default)
                        .tooltip(if is_role_default {
                            "She already has the recommended tools for her role"
                        } else {
                            "Drop her own list and use the recommended tools for her role"
                        })
                        .when(editor.confirm_reset, |b| b.danger().label("Drop her list and reset"))
                        .when(!editor.confirm_reset, |b| b.label("Reset to recommended"))
                        .on_click(cx.listener(|this, _, _, cx| {
                            let Some(editor) = this.current() else { return };
                            if editor.confirm_reset {
                                this.save(true, cx);
                            } else {
                                editor.confirm_reset = true;
                                cx.notify();
                            }
                        })),
                )
            });

        v_flex()
            .gap_2()
            .child(
                h_flex()
                    .justify_between()
                    .child(div().text_xs().text_color(theme.muted_foreground).child(if is_queen && is_role_default { "Using the recommended tools for her role." } else { "" }))
                    .child(div().text_xs().text_color(theme.muted_foreground).child(format!("{} always on · {searchable_on}/{searchable_total} searchable", system_count + locked_count))),
            )
            .when(!is_queen, |col| col.child(div().px_3().py_2().rounded_md().bg(theme.muted).text_xs().child("Changes apply to the next worker spawn. Running workers keep the tools they started with.")))
            .when(flag(snapshot, "stale"), |col| col.child(div().px_3().py_2().rounded_md().bg(theme.muted).text_xs().child("The tool catalog isn't available yet. Start a session once to fill it.")))
            .child(tier("Built-in capabilities", format!("{} tools", system_count + locked_count), "The agent always has these. They can't be turned off."))
            .children(locked_groups)
            .when(!open_groups.is_empty(), |col| {
                col.child(tier(
                    "Searchable",
                    format!("{searchable_on}/{searchable_total} available"),
                    "The agent sees these by name and loads one with search_tools when a task needs it. Turn a tool off to hide it from the agent.",
                ))
                .children(open_groups)
            })
            .child(actions)
            .when_some(editor.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .into_any_element()
    }

    fn render_server(&self, server: &Value, ix: usize, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let name = text(server, "name");
        let transport = text(server, "transport");
        let builtin = text(server, "source") == "built-in";
        let local = text(server, "source") == "local" && server["removable"] != Value::Bool(false);
        let enabled = flag(server, "enabled");
        let cli = text(server, "mode") == "cli";
        let busy = self.busy.contains(&name);
        let confirming = self.confirm_remove.as_deref() == Some(name.as_str());
        let (health_icon, health, health_color) = match (enabled, text(server, "last_health_status").as_str()) {
            (false, _) => (IconName::CircleDashed, "Disabled", theme.muted_foreground),
            (true, "healthy") => (IconName::CircleCheck, "Healthy", theme.success),
            (true, "unhealthy") => (IconName::CircleAlert, "Unhealthy", theme.danger),
            _ => (IconName::CircleDashed, "Unknown", theme.muted_foreground),
        };
        let last_error = text(server, "last_error");
        let tag = |label: String| {
            div().px_1p5().rounded_sm().bg(theme.muted).text_xs().text_color(theme.muted_foreground).child(label)
        };
        let info = v_flex()
            .flex_1()
            .min_w_0()
            .child(
                h_flex()
                    .gap_2()
                    .child(div().text_sm().font_medium().truncate().child(name.clone()))
                    .child(tag(transport.clone()))
                    .when(builtin, |row| row.child(tag("built-in".into())))
                    .when(cli, |row| row.child(tag("CLI".into())))
                    .when_some(server["tool_count"].as_i64(), |row, n| {
                        row.child(
                            div()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(format!("{n} {}", if cli { "commands" } else { "tools" })),
                        )
                    }),
            )
            .child(
                h_flex()
                    .gap_2()
                    .text_xs()
                    .text_color(theme.muted_foreground)
                    .when(!builtin, |row| {
                        row.child(
                            h_flex()
                                .gap_1()
                                .text_color(health_color)
                                .child(Icon::new(health_icon).xsmall())
                                .child(health),
                        )
                    })
                    .child(div().truncate().child(text(server, "description"))),
            )
            .when(!builtin && enabled && health == "Unhealthy" && !last_error.is_empty(), |col| {
                col.child(ui::error_line(ui::clip(&last_error, 200), &theme).text_xs())
            });

        let actions = h_flex()
            .gap_1()
            .flex_shrink_0()
            .when(!builtin && transport != "unix", |row| {
                let name = name.clone();
                row.child(
                    Button::new(("mode", ix))
                        .small()
                        .ghost()
                        .label(if cli { "Use as tools" } else { "Use from terminal" })
                        .tooltip(if cli {
                            "Load its tools into agents' tool lists instead"
                        } else {
                            "Keep its tools out of prompts; agents run it from the terminal"
                        })
                        .disabled(busy)
                        .on_click(cx.listener(move |this, _, _, cx| {
                            let name = name.clone();
                            let mode = if cli { "tools" } else { "cli" };
                            this.server_write(
                                name.clone(),
                                move |api| {
                                    api.post(&format!("/mcp/servers/{}/mode", encode(&name)), json!({ "mode": mode }))
                                },
                                cx,
                            );
                        })),
                )
            })
            .when(!builtin, |row| {
                let check = name.clone();
                let toggle = name.clone();
                row.child(
                    Button::new(("health", ix))
                        .small()
                        .ghost()
                        .icon(IconName::RefreshCw)
                        .tooltip("Check its health")
                        .loading(busy)
                        .on_click(cx.listener(move |this, _, _, cx| {
                            let name = check.clone();
                            this.server_write(
                                name.clone(),
                                move |api| api.post(&format!("/mcp/servers/{}/health", encode(&name)), json!({})),
                                cx,
                            );
                        })),
                )
                .child(
                    Button::new(("enable", ix))
                        .small()
                        .outline()
                        .label(if enabled { "Disable" } else { "Enable" })
                        .disabled(busy)
                        .on_click(cx.listener(move |this, _, _, cx| {
                            let name = toggle.clone();
                            let action = if enabled { "disable" } else { "enable" };
                            this.server_write(
                                name.clone(),
                                move |api| api.post(&format!("/mcp/servers/{}/{action}", encode(&name)), json!({})),
                                cx,
                            );
                        })),
                )
            })
            .when(local, |row| {
                let name = name.clone();
                row.child(
                    Button::new(("remove", ix))
                        .small()
                        .ghost()
                        .disabled(busy)
                        .when(confirming, |b| b.danger().label("Remove this server"))
                        .when(!confirming, |b| b.icon(IconName::Trash).tooltip("Remove"))
                        .on_click(cx.listener(move |this, _, _, cx| {
                            if this.confirm_remove.as_deref() == Some(name.as_str()) {
                                let name = name.clone();
                                this.server_write(
                                    name.clone(),
                                    move |api| api.delete(&format!("/mcp/servers/{}", encode(&name))),
                                    cx,
                                );
                            } else {
                                this.confirm_remove = Some(name.clone());
                                cx.notify();
                            }
                        })),
                )
            });

        ui::card(&theme)
            .child(
                div()
                    .size(px(32.))
                    .flex_shrink_0()
                    .rounded_full()
                    .flex()
                    .items_center()
                    .justify_center()
                    .bg(theme.muted)
                    .child(Icon::new(IconName::Server).small()),
            )
            .child(info)
            .child(actions)
            .into_any_element()
    }

    fn render_add(&self, form: &AddForm, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let field = |label: &'static str, element: AnyElement| {
            v_flex()
                .gap_1()
                .child(div().text_xs().font_medium().text_color(theme.muted_foreground).child(label))
                .child(element)
        };
        let typed = form.name.read(cx).value().trim().to_string();
        let saved_as = sanitize_name(&typed);
        let transports = h_flex().gap_1().children(["stdio", "http", "sse", "unix"].into_iter().map(|t| {
            Button::new(SharedString::from(format!("transport-{t}")))
                .small()
                .ghost()
                .label(t)
                .selected(form.transport == t)
                .on_click(cx.listener(move |this, _, _, cx| {
                    if let Some(form) = this.add.as_mut() {
                        form.transport = t;
                    }
                    cx.notify();
                }))
        }));
        let modes = h_flex().gap_1().children([("tools", "As tools"), ("cli", "From the terminal")].into_iter().map(
            |(m, label)| {
                Button::new(SharedString::from(format!("mode-{m}")))
                    .small()
                    .ghost()
                    .label(label)
                    .selected(form.mode == m)
                    .on_click(cx.listener(move |this, _, _, cx| {
                        if let Some(form) = this.add.as_mut() {
                            form.mode = m;
                        }
                        cx.notify();
                    }))
            },
        ));
        let mode_hint = if form.mode == "cli" {
            format!(
                "They run “hive mcp run {} …” in the terminal. Its tools stay out of every prompt until a command is used, which suits servers with many tools.",
                if saved_as.is_empty() { "<name>" } else { saved_as.as_str() }
            )
        } else {
            "Its tools load into every agent's tool list.".to_string()
        };
        v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(div().text_sm().font_semibold().child("Add an MCP server"))
            .child(field("Name", Input::new(&form.name).small().into_any_element()).when(
                !typed.is_empty() && saved_as != typed,
                |col| {
                    col.child(
                        ui::muted(format!("Saved as “{saved_as}”: lowercase letters, digits, - and _ only."), &theme)
                            .text_xs(),
                    )
                },
            ))
            .child(field("Transport", transports.into_any_element()))
            .when(form.transport == "stdio", |col| {
                col.child(field("Command", Input::new(&form.command).small().into_any_element()))
                    .child(field("Arguments, one per line", Textarea::new(&form.args).into_any_element()))
                    .child(field("Environment, KEY=VALUE per line", Textarea::new(&form.env).into_any_element()))
                    .child(field("Working folder", Input::new(&form.cwd).small().into_any_element()))
            })
            .when(form.transport == "http" || form.transport == "sse", |col| {
                col.child(field("URL", Input::new(&form.url).small().into_any_element()))
                    .child(field("Headers, KEY=VALUE per line", Textarea::new(&form.headers).into_any_element()))
            })
            .when(form.transport == "unix", |col| {
                col.child(field("Socket path", Input::new(&form.socket).small().into_any_element()))
            })
            .when(form.transport != "unix", |col| {
                col.child(field(
                    "Agents use it",
                    v_flex().gap_1().child(modes).child(ui::muted(mode_hint, &theme).text_xs()).into_any_element(),
                ))
            })
            .child(field("Description", Input::new(&form.description).small().into_any_element()))
            .when_some(form.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .child(
                h_flex()
                    .gap_2()
                    .justify_end()
                    .child(
                        Button::new("add-cancel").small().ghost().label("Cancel").disabled(form.submitting).on_click(
                            cx.listener(|this, _, _, cx| {
                                this.add = None;
                                cx.notify();
                            }),
                        ),
                    )
                    .child(
                        Button::new("add-server")
                            .small()
                            .primary()
                            .icon(IconName::Check)
                            .label("Add")
                            .loading(form.submitting)
                            .on_click(cx.listener(|this, _, _, cx| this.submit_add(cx))),
                    ),
            )
            .into_any_element()
    }

    fn render_mcp(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let add = self.add.as_ref().map(|form| self.render_add(form, cx));
        let list = match &self.servers {
            None => Spinner::new().into_any_element(),
            Some(Err(e)) => ui::error_line(format!("Couldn't load MCP servers: {e}"), &theme).into_any_element(),
            Some(Ok(servers)) => {
                let (custom, builtin): (Vec<_>, Vec<_>) =
                    servers.iter().enumerate().partition(|(_, s)| text(s, "source") == "local");
                let custom: Vec<AnyElement> = custom.into_iter().map(|(ix, s)| self.render_server(s, ix, cx)).collect();
                let builtin: Vec<AnyElement> =
                    builtin.into_iter().map(|(ix, s)| self.render_server(s, ix, cx)).collect();
                v_flex()
                    .gap_6()
                    .when(!custom.is_empty(), |col| col.child(ui::section("My custom", &theme).children(custom)))
                    .child(
                        ui::section("Built-in", &theme)
                            .when(builtin.is_empty(), |col| {
                                col.child(ui::muted("No built-in servers registered.", &theme))
                            })
                            .children(builtin),
                    )
                    .into_any_element()
            }
        };
        v_flex()
            .gap_4()
            .child(
                h_flex()
                    .gap_2()
                    .child(
                        Button::new("toggle-add")
                            .small()
                            .primary()
                            .icon(IconName::Plus)
                            .label("Add an MCP server")
                            .selected(self.add.is_some())
                            .on_click(cx.listener(|this, _, window, cx| this.toggle_add(window, cx))),
                    )
                    .child(
                        Button::new("refresh-servers")
                            .small()
                            .ghost()
                            .icon(IconName::RefreshCw)
                            .tooltip("Refresh")
                            .on_click(cx.listener(|this, _, _, cx| this.load_servers(cx))),
                    ),
            )
            .children(add)
            .when_some(self.mcp_error.clone(), |col, e| {
                col.child(h_flex().gap_2().child(ui::error_line(e, &theme).flex_1()).child(
                    Button::new("dismiss-error").xsmall().ghost().icon(IconName::X).on_click(cx.listener(
                        |this, _, _, cx| {
                            this.mcp_error = None;
                            cx.notify();
                        },
                    )),
                ))
            })
            .child(list)
            .into_any_element()
    }
}

/// "Name · Role", which tells apart two queens of the same name.
fn queen_label(queen: &Queen) -> String {
    let role = ui::role(&queen.title);
    if role.is_empty() { queen.name.clone() } else { format!("{} · {role}", queen.name) }
}

impl Render for ToolsPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) = ui::page(
            "tools-body",
            "Tools",
            "Choose the tools each queen and colony can use, and connect your own MCP servers.",
            &theme,
        );
        let tab_button =
            |id: &'static str, tab: Tab, icon: IconName, label: &'static str, this: &Self, cx: &mut Context<Self>| {
                Button::new(id).small().ghost().icon(icon).label(label).selected(this.tab == tab).on_click(cx.listener(
                    move |this, _, _, cx| {
                        this.tab = tab;
                        cx.notify();
                    },
                ))
            };
        let tabs = h_flex()
            .gap_1()
            .child(tab_button("tab-queens", Tab::Queens, IconName::Crown, "By queen", self, cx))
            .child(tab_button("tab-colonies", Tab::Colonies, IconName::Network, "By colony", self, cx))
            .child(tab_button("tab-mcp", Tab::Mcp, IconName::Server, "MCP servers", self, cx));

        let content: AnyElement = match self.tab {
            Tab::Mcp => self.render_mcp(cx),
            tab => {
                let (loaded, empty, editor) = match tab {
                    Tab::Queens => (
                        self.queens.as_ref().map(|q| q.as_ref().map(|q| q.is_empty())),
                        "No queens yet. Create one to choose her tools.",
                        self.queen_editor.as_ref(),
                    ),
                    _ => (
                        self.colonies.as_ref().map(|c| c.as_ref().map(|c| c.is_empty())),
                        "No colonies yet. Ask a queen to start one and its tools show up here.",
                        self.colony_editor.as_ref(),
                    ),
                };
                match loaded {
                    None => Spinner::new().into_any_element(),
                    Some(Err(e)) => ui::error_line(format!("Couldn't load the list: {e}"), &theme).into_any_element(),
                    Some(Ok(true)) => ui::muted(empty, &theme).into_any_element(),
                    Some(Ok(false)) => {
                        let picker = self.render_picker(cx);
                        v_flex()
                            .gap_4()
                            .child(h_flex().child(picker))
                            .when_some(editor, |col, editor| col.child(self.render_editor(editor, cx)))
                            .into_any_element()
                    }
                }
            }
        };
        let content = v_flex().gap_4().px_8().py_6().w_full().max_w(px(880.)).mx_auto().child(tabs).child(content);
        v_flex().size_full().child(header).child(body.child(content))
    }
}

#[cfg(test)]
mod tests {
    // Not a glob: `gpui_kit::*` brings a `test` attribute of its own.
    use super::{groups, key_values, sanitize_name, title_case};
    use serde_json::json;

    #[test]
    fn errors_keep_unknown_names_and_fix() {}

    #[test]
    fn names_are_sanitized() {
        assert_eq!(sanitize_name("My Search_Tool-2!"), "mysearch_tool-2");
    }

    #[test]
    fn key_value_lines() {
        let map = key_values("API_KEY=abc=1\n\nnot a pair\n =skipped\n MODE = fast ");
        assert_eq!(map.len(), 2);
        assert_eq!(map["API_KEY"], "abc=1");
        assert_eq!(map["MODE"], "fast");
    }

    #[test]
    fn tools_group_by_category_then_server() {
        let snapshot = json!({
            "categories": [
                {"name": "file_ops", "tools": ["read_file"], "always_enabled": true},
                {"name": "charts", "tools": ["chart_render", "read_file"]},
                {"name": "empty_one", "tools": []},
            ],
            "mcp_servers": [
                {"name": "ava-tools", "tools": [
                    {"name": "read_file", "description": ""},
                    {"name": "chart_render", "description": ""},
                    {"name": "zed_ping", "description": ""},
                    {"name": "mira_mail", "description": "", "provider": "google"},
                ]},
            ],
        });
        let groups = groups(&snapshot);
        let summary: Vec<(String, bool, Vec<String>)> = groups
            .iter()
            .map(|g| (g.title.clone(), g.locked, g.tools.iter().map(|(n, _)| n.clone()).collect()))
            .collect();
        assert_eq!(
            summary,
            vec![
                ("Files & documents".into(), true, vec!["read_file".into()]),
                ("Charts & diagrams".into(), false, vec!["chart_render".into()]),
                ("Ava Tools".into(), false, vec!["zed_ping".into()]),
            ]
        );
        assert_eq!(title_case("terminal-tools"), "Terminal Tools");
    }
}
