//! The skill library: every SKILL.md the queens can use, and which ones each queen has on.
//! Mirrors `frontend/src/pages/skills-library.tsx` and `components/ExternalSkillSources.tsx`.

use std::path::PathBuf;

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};
use gpui_kit::component::menu::{DropdownMenu as _, PopupMenuItem};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::{flag, text};
use crate::api::{Api, FilePart, Queen, api, encode};
use crate::{bg, ui};

/// The largest upload the server takes.
const MAX_UPLOAD: u64 = 2 * 1024 * 1024;

/// How much of a description a row shows.
const DESCRIPTION_CLIP: usize = 180;

/// The skill opened under its row.
struct Opened {
    name: String,
    /// Her copy (frontmatter stripped) with a queen picked, else the library's.
    detail: Option<Result<Value, String>>,
    raw: bool,
    copied: bool,
    /// The description and body fields, while editing.
    edit: Option<(Entity<InputState>, Entity<TextareaState>)>,
    rename: Option<Entity<InputState>>,
    confirm_delete: bool,
    busy: bool,
    error: Option<String>,
}

impl Opened {
    fn new(name: String) -> Self {
        Self {
            name,
            detail: None,
            raw: false,
            copied: false,
            edit: None,
            rename: None,
            confirm_delete: false,
            busy: false,
            error: None,
        }
    }
}

struct NewSkill {
    name: Entity<InputState>,
    description: Entity<InputState>,
    body: Entity<TextareaState>,
    saving: bool,
    error: Option<String>,
}

struct Upload {
    /// The chosen file and its size in bytes.
    file: Option<(PathBuf, u64)>,
    /// The queen it's for; `None` adds it for all queens.
    target: Option<String>,
    enabled: bool,
    uploading: bool,
    error: Option<String>,
    /// The server's same-name message, while Replace is offered.
    conflict: Option<String>,
}

/// Extra skill folders from other agents (`external_skills` in the config).
struct Sources {
    loaded: Option<Result<Value, String>>,
    open: bool,
    draft: Entity<InputState>,
    /// A path the user asked to remove; a second click confirms.
    confirm_remove: Option<String>,
    saving: bool,
    error: Option<String>,
}

pub struct SkillsPage {
    queens: Vec<Queen>,
    library: Option<Result<Value, String>>,
    /// The queen being configured; `None` browses every skill.
    queen: Option<String>,
    /// Her skills with their on/off state, once loaded.
    rows: Option<Vec<Value>>,
    search: Entity<InputState>,
    show_inactive: bool,
    opened: Option<Opened>,
    new_skill: Option<NewSkill>,
    upload: Option<Upload>,
    sources: Sources,
    tasks: Vec<Task<()>>,
}

/// The body without its leading `---` YAML block, as the rendered view shows it.
fn strip_frontmatter(body: &str) -> &str {
    let Some(rest) = body.trim_start().strip_prefix("---") else { return body };
    let Some(rest) = rest.strip_prefix("\r\n").or_else(|| rest.strip_prefix('\n')) else { return body };
    let mut offset = 0;
    for line in rest.split_inclusive('\n') {
        offset += line.len();
        if line.trim_end() == "---" {
            return &rest[offset..];
        }
    }
    body
}

fn is_upload(path: &std::path::Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| e.eq_ignore_ascii_case("md") || e.eq_ignore_ascii_case("zip"))
}

fn size_label(bytes: u64) -> String {
    match bytes {
        0..1024 => format!("{bytes} B"),
        1024..1_048_576 => format!("{:.1} KB", bytes as f64 / 1024.0),
        _ => format!("{:.1} MB", bytes as f64 / 1_048_576.0),
    }
}

impl SkillsPage {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search skills"));
        cx.observe(&search, |_, _, cx| cx.notify()).detach();
        let draft = cx.new(|cx| InputState::new(window, cx).placeholder("Add a folder, e.g. ~/.claude/skills"));
        let mut page = Self {
            queens: Vec::new(),
            library: None,
            queen: None,
            rows: None,
            search,
            show_inactive: false,
            opened: None,
            new_skill: None,
            upload: None,
            sources: Sources { loaded: None, open: false, draft, confirm_remove: None, saving: false, error: None },
            tasks: Vec::new(),
        };
        page.load(cx);
        page.load_sources(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        let queen = self.queen.clone();
        self.tasks.push(bg::spawn(
            cx,
            {
                let queen = queen.clone();
                move || {
                    let library = api.get("/skills")?;
                    let queens = api.queens()?;
                    let rows = match &queen {
                        Some(id) => Some(
                            api.get(&format!("/queen/{}/skills", encode(id)))?["skills"]
                                .as_array()
                                .cloned()
                                .unwrap_or_default(),
                        ),
                        None => None,
                    };
                    anyhow::Ok((library, queens, rows))
                }
            },
            move |this: &mut Self, loaded, _| {
                // Picking another queen meanwhile started its own load.
                if this.queen != queen {
                    return;
                }
                match loaded {
                    Ok((library, queens, rows)) => {
                        this.library = Some(Ok(library));
                        this.queens = queens;
                        this.rows = rows;
                    }
                    Err(e) => this.library = Some(Err(e.to_string())),
                }
            },
        ));
    }

    fn pick_queen(&mut self, queen: Option<String>, cx: &mut Context<Self>) {
        if self.queen == queen {
            return;
        }
        self.queen = queen;
        self.rows = None;
        self.opened = None;
        self.new_skill = None;
        self.show_inactive = false;
        self.load(cx);
        cx.notify();
    }

    fn open(&mut self, name: String, cx: &mut Context<Self>) {
        if self.opened.as_ref().is_some_and(|o| o.name == name) {
            self.opened = None;
        } else {
            self.opened = Some(Opened::new(name));
            self.fetch_detail(cx);
        }
        cx.notify();
    }

    fn fetch_detail(&mut self, cx: &mut Context<Self>) {
        let Some(name) = self.opened.as_ref().map(|o| o.name.clone()) else { return };
        let path = match &self.queen {
            Some(queen) => format!("/queen/{}/skills/{}/body", encode(queen), encode(&name)),
            None => format!("/skills/{}", encode(&name)),
        };
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get(&path),
            move |this: &mut Self, detail, _| {
                if let Some(opened) = this.opened.as_mut().filter(|o| o.name == name) {
                    opened.detail = Some(detail.map_err(|e| e.to_string()));
                }
            },
        ));
    }

    /// Run a write on the opened skill, then `then` once it worked; a failure shows in the skill's panel.
    fn write_opened(
        &mut self,
        work: impl FnOnce(Api) -> anyhow::Result<Value> + Send + 'static,
        then: impl FnOnce(&mut Self, &mut Context<Self>) + 'static,
        cx: &mut Context<Self>,
    ) {
        if let Some(opened) = self.opened.as_mut() {
            opened.busy = true;
            opened.error = None;
        }
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || work(api),
            move |this: &mut Self, done, cx| {
                if let Some(opened) = this.opened.as_mut() {
                    opened.busy = false;
                }
                match done {
                    Ok(_) => then(this, cx),
                    Err(e) => {
                        if let Some(opened) = this.opened.as_mut() {
                            opened.error = Some(e.to_string());
                        }
                    }
                }
            },
        ));
        cx.notify();
    }

    /// `/queen/{id}/skills/{name}` for the picked queen and the opened skill.
    fn opened_path(&self) -> Option<String> {
        Some(format!("/queen/{}/skills/{}", encode(self.queen.as_ref()?), encode(&self.opened.as_ref()?.name)))
    }

    fn set_enabled(&mut self, enabled: bool, cx: &mut Context<Self>) {
        let Some(path) = self.opened_path() else { return };
        self.write_opened(move |api| api.patch(&path, json!({ "enabled": enabled })), |this, cx| this.load(cx), cx);
    }

    fn start_edit(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(Some(Ok(detail))) = self.opened.as_ref().map(|o| o.detail.clone()) else { return };
        let description = cx.new(|cx| InputState::new(window, cx).default_value(text(&detail, "description")));
        let body = cx.new(|cx| TextareaState::new(window, cx).auto_grow(12, 40).default_value(text(&detail, "body")));
        body.update(cx, |state, cx| state.focus(window, cx));
        if let Some(opened) = self.opened.as_mut() {
            opened.edit = Some((description, body));
            opened.rename = None;
        }
        cx.notify();
    }

    fn save_edit(&mut self, cx: &mut Context<Self>) {
        let (Some(path), Some((description, body))) =
            (self.opened_path(), self.opened.as_ref().and_then(|o| o.edit.clone()))
        else {
            return;
        };
        let payload =
            json!({ "body": body.read(cx).value().to_string(), "description": description.read(cx).value().trim() });
        self.write_opened(
            move |api| api.put(&format!("{path}/body"), payload),
            |this, cx| {
                if let Some(opened) = this.opened.as_mut() {
                    opened.edit = None;
                    opened.detail = None;
                }
                this.fetch_detail(cx);
                this.load(cx);
            },
            cx,
        );
    }

    fn start_rename(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(name) = self.opened.as_ref().map(|o| o.name.clone()) else { return };
        let field = cx.new(|cx| InputState::new(window, cx).default_value(name).placeholder("new-skill-name"));
        field.update(cx, |state, cx| state.focus(window, cx));
        if let Some(opened) = self.opened.as_mut() {
            opened.rename = Some(field);
            opened.edit = None;
        }
        cx.notify();
    }

    fn submit_rename(&mut self, cx: &mut Context<Self>) {
        let (Some(path), Some(opened)) = (self.opened_path(), self.opened.as_mut()) else { return };
        let Some(field) = opened.rename.clone() else { return };
        let new_name = field.read(cx).value().trim().to_string();
        if new_name.is_empty() || new_name == opened.name {
            opened.rename = None;
            cx.notify();
            return;
        }
        let renamed = new_name.clone();
        self.write_opened(
            move |api| api.post(&format!("{path}/rename"), json!({ "new_name": new_name })),
            move |this, cx| {
                // The old name is gone, so the panel follows the skill to its new one.
                this.opened = Some(Opened::new(renamed));
                this.fetch_detail(cx);
                this.load(cx);
            },
            cx,
        );
    }

    fn delete_opened(&mut self, cx: &mut Context<Self>) {
        let (Some(path), Some(opened)) = (self.opened_path(), self.opened.as_mut()) else { return };
        if !opened.confirm_delete {
            opened.confirm_delete = true;
            cx.notify();
            return;
        }
        self.write_opened(
            move |api| api.delete(&path),
            |this, cx| {
                this.opened = None;
                this.load(cx);
            },
            cx,
        );
    }

    fn toggle_new(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.new_skill.take().is_none() {
            let name = cx.new(|cx| InputState::new(window, cx).placeholder("vendor-api-protocol"));
            let description = cx.new(|cx| InputState::new(window, cx).placeholder("One line on when to use it"));
            let body = cx.new(|cx| {
                TextareaState::new(window, cx).auto_grow(10, 30).placeholder("## When to use\n\n…\n\n## Steps\n\n1. …")
            });
            name.update(cx, |state, cx| state.focus(window, cx));
            self.new_skill = Some(NewSkill { name, description, body, saving: false, error: None });
            self.upload = None;
        }
        cx.notify();
    }

    fn create(&mut self, cx: &mut Context<Self>) {
        let (Some(queen), Some(form)) = (self.queen.clone(), self.new_skill.as_mut()) else { return };
        let name = form.name.read(cx).value().trim().to_lowercase();
        let description = form.description.read(cx).value().trim().to_string();
        let body = form.body.read(cx).value().to_string();
        if name.is_empty() || description.is_empty() || body.trim().is_empty() {
            form.error = Some("A skill needs a name, a description and a body.".into());
            cx.notify();
            return;
        }
        form.saving = true;
        form.error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                api.post(
                    &format!("/queen/{}/skills", encode(&queen)),
                    json!({ "name": name, "description": description, "body": body, "enabled": true }),
                )
            },
            |this: &mut Self, done, cx| match done {
                Ok(_) => {
                    this.new_skill = None;
                    this.load(cx);
                }
                Err(e) => {
                    if let Some(form) = this.new_skill.as_mut() {
                        form.saving = false;
                        form.error = Some(e.to_string());
                    }
                }
            },
        ));
        cx.notify();
    }

    fn toggle_upload(&mut self, cx: &mut Context<Self>) {
        if self.upload.take().is_none() {
            self.upload = Some(Upload {
                file: None,
                target: self.queen.clone(),
                enabled: true,
                uploading: false,
                error: None,
                conflict: None,
            });
            self.new_skill = None;
        }
        cx.notify();
    }

    fn choose_file(&mut self, cx: &mut Context<Self>) {
        let picked = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some("Choose a SKILL.md or a .zip".into()),
        });
        self.tasks.push(cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(paths))) = picked.await else { return };
            let Some(path) = paths.into_iter().next() else { return };
            let size = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
            this.update(cx, |this, cx| {
                let Some(upload) = this.upload.as_mut() else { return };
                upload.conflict = None;
                if is_upload(&path) {
                    upload.file = Some((path, size));
                    upload.error = None;
                } else {
                    upload.error = Some("Only .md or .zip files can be uploaded.".into());
                }
                cx.notify();
            })
            .ok();
        }));
    }

    fn upload(&mut self, replace: bool, cx: &mut Context<Self>) {
        let Some(upload) = self.upload.as_mut() else { return };
        let Some((path, _)) = upload.file.clone() else {
            upload.error = Some("Choose a .md or .zip file first.".into());
            cx.notify();
            return;
        };
        let target = upload.target.clone();
        let enabled = upload.enabled;
        upload.uploading = true;
        upload.error = None;
        upload.conflict = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let bytes = std::fs::read(&path)?;
                if bytes.len() as u64 > MAX_UPLOAD {
                    anyhow::bail!("That file is over 2 MB, the most the server takes.");
                }
                let filename = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
                let zip = filename.to_lowercase().ends_with(".zip");
                let mut fields = vec![
                    ("scope", if target.is_some() { "queen" } else { "user" }),
                    ("enabled", if enabled { "true" } else { "false" }),
                    ("replace_existing", if replace { "true" } else { "false" }),
                ];
                if let Some(queen) = &target {
                    fields.push(("target_id", queen));
                }
                let file = FilePart {
                    field: "file".into(),
                    filename,
                    content_type: if zip { "application/zip" } else { "text/markdown" }.into(),
                    bytes,
                };
                api.post_multipart("/skills/upload", &fields, Some(file))
            },
            |this: &mut Self, done, cx| {
                let Some(upload) = this.upload.as_mut() else { return };
                upload.uploading = false;
                match done {
                    Ok(_) => {
                        this.upload = None;
                        this.load(cx);
                    }
                    // A skill of that name already there isn't a failure: the user may replace it.
                    Err(e) => match e.to_string().strip_prefix("HTTP 409: ") {
                        Some(message) => upload.conflict = Some(message.to_string()),
                        None => upload.error = Some(e.to_string()),
                    },
                }
            },
        ));
        cx.notify();
    }

    fn load_sources(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/config/external-skills"),
            |this: &mut Self, loaded, _| this.sources.loaded = Some(loaded.map_err(|e| e.to_string())),
        ));
    }

    fn source_paths(&self) -> Vec<String> {
        match &self.sources.loaded {
            Some(Ok(v)) => {
                v["paths"].as_array().into_iter().flatten().filter_map(|p| p.as_str().map(str::to_string)).collect()
            }
            _ => Vec::new(),
        }
    }

    /// Write the whole source list, then reread it (for the suggestions) and the skills it brings.
    fn save_sources(&mut self, paths: Vec<String>, cx: &mut Context<Self>) {
        self.sources.saving = true;
        self.sources.error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                api.put("/config/external-skills", json!({ "paths": paths }))?;
                api.get("/config/external-skills")
            },
            |this: &mut Self, done, cx| {
                this.sources.saving = false;
                this.sources.confirm_remove = None;
                match done {
                    Ok(v) => {
                        this.sources.loaded = Some(Ok(v));
                        this.load(cx);
                    }
                    Err(e) => this.sources.error = Some(e.to_string()),
                }
            },
        ));
        cx.notify();
    }

    fn add_source(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let path = self.sources.draft.read(cx).value().trim().to_string();
        let mut paths = self.source_paths();
        if path.is_empty() || paths.contains(&path) {
            return;
        }
        self.sources.draft.update(cx, |s, cx| s.set_value("", window, cx));
        paths.push(path);
        self.save_sources(paths, cx);
    }

    fn render_queen_picker(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let page = cx.entity().downgrade();
        let queens: Vec<(String, String)> = self.queens.iter().map(|q| (q.id.clone(), queen_label(q))).collect();
        let current = self.queen.clone();
        let label = match current.as_ref().and_then(|id| self.queens.iter().find(|q| &q.id == id)) {
            Some(q) => format!("Configuring: {}", queen_label(q)),
            None => "All skills".to_string(),
        };
        Button::new("queen-picker").small().outline().label(label).dropdown_caret(true).dropdown_menu(
            move |menu, _, _| {
                let all = page.clone();
                let mut menu =
                    menu.item(PopupMenuItem::new("All skills").checked(current.is_none()).on_click(move |_, _, cx| {
                        all.update(cx, |this, cx| this.pick_queen(None, cx)).ok();
                    }));
                menu = menu.separator();
                for (id, label) in &queens {
                    let page = page.clone();
                    let pick = id.clone();
                    menu = menu.item(PopupMenuItem::new(label.clone()).checked(current.as_ref() == Some(id)).on_click(
                        move |_, _, cx| {
                            page.update(cx, |this, cx| this.pick_queen(Some(pick.clone()), cx)).ok();
                        },
                    ));
                }
                menu.max_h(px(420.)).scrollable(true)
            },
        )
    }

    fn render_opened(&self, opened: &Opened, row: Option<&Value>, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let name = opened.name.clone();
        let mut panel = v_flex().gap_3().p_4().rounded_lg().border_1().border_color(theme.border).bg(theme.sidebar);

        // Turning a skill on or off, and changing it, happen for the picked queen only.
        if let Some(row) = row.filter(|_| self.queen.is_some()) {
            let enabled = flag(row, "enabled");
            let editable = flag(row, "editable");
            let idle = opened.edit.is_none() && opened.rename.is_none();
            panel = panel.child(
                h_flex()
                    .gap_3()
                    .child(
                        Switch::new("skill-enabled")
                            .checked(enabled)
                            .disabled(opened.busy)
                            .on_click(cx.listener(|this, checked: &bool, _, cx| this.set_enabled(*checked, cx))),
                    )
                    .child(
                        div()
                            .text_sm()
                            .font_medium()
                            .text_color(if enabled { theme.success } else { theme.muted_foreground })
                            .child(if enabled { "Active" } else { "Inactive" }),
                    )
                    .when(opened.busy, |row| row.child(Spinner::new().small()))
                    .child(div().flex_1())
                    .when(editable && idle, |row| {
                        row.child(
                            Button::new("edit-skill")
                                .small()
                                .ghost()
                                .icon(IconName::Pencil)
                                .label("Edit")
                                .disabled(!matches!(opened.detail, Some(Ok(_))))
                                .on_click(cx.listener(|this, _, window, cx| this.start_edit(window, cx))),
                        )
                        .child(
                            Button::new("rename-skill")
                                .small()
                                .ghost()
                                .label("Rename")
                                .on_click(cx.listener(|this, _, window, cx| this.start_rename(window, cx))),
                        )
                    })
                    .when(flag(row, "deletable") && idle, |row| {
                        row.child(
                            Button::new("delete-skill")
                                .small()
                                .ghost()
                                .when(opened.confirm_delete, |b| b.danger().label("Delete its files for good"))
                                .when(!opened.confirm_delete, |b| b.icon(IconName::Trash).label("Delete"))
                                .on_click(cx.listener(|this, _, _, cx| this.delete_opened(cx))),
                        )
                    })
                    .when(!editable, |row| {
                        row.child(
                            h_flex()
                                .gap_1()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(Icon::new(IconName::Lock).xsmall())
                                .child("Read-only"),
                        )
                    }),
            );
        }

        if let Some(field) = &opened.rename {
            panel = panel.child(
                v_flex()
                    .gap_2()
                    .child(Input::new(field).small())
                    .child(
                        ui::muted("Renames only this queen's copy. Other queens keep the old name.", &theme).text_xs(),
                    )
                    .child(
                        h_flex()
                            .gap_2()
                            .child(
                                Button::new("rename-save")
                                    .small()
                                    .primary()
                                    .label("Rename")
                                    .loading(opened.busy)
                                    .on_click(cx.listener(|this, _, _, cx| this.submit_rename(cx))),
                            )
                            .child(Button::new("rename-cancel").small().ghost().label("Cancel").on_click(cx.listener(
                                |this, _, _, cx| {
                                    if let Some(opened) = this.opened.as_mut() {
                                        opened.rename = None;
                                    }
                                    cx.notify();
                                },
                            ))),
                    ),
            );
        }

        if let Some(e) = &opened.error {
            panel = panel.child(ui::error_line(e.clone(), &theme));
        }

        let detail = match &opened.detail {
            None => return panel.child(Spinner::new().small()).into_any_element(),
            Some(Err(e)) => {
                return panel
                    .child(ui::error_line(format!("Couldn't load this skill: {e}"), &theme))
                    .into_any_element();
            }
            Some(Ok(detail)) => detail,
        };

        if let Some((description, body)) = &opened.edit {
            return panel
                .child(
                    v_flex()
                        .gap_1()
                        .child(div().text_xs().font_medium().text_color(theme.muted_foreground).child("Description"))
                        .child(Input::new(description).small()),
                )
                .child(
                    v_flex()
                        .gap_1()
                        .child(div().text_xs().font_medium().text_color(theme.muted_foreground).child("SKILL.md"))
                        .child(Textarea::new(body)),
                )
                .child(
                    h_flex()
                        .gap_2()
                        .child(
                            Button::new("edit-save")
                                .small()
                                .primary()
                                .icon(IconName::Check)
                                .label("Save")
                                .loading(opened.busy)
                                .on_click(cx.listener(|this, _, _, cx| this.save_edit(cx))),
                        )
                        .child(Button::new("edit-cancel").small().ghost().label("Cancel").on_click(cx.listener(
                            |this, _, _, cx| {
                                if let Some(opened) = this.opened.as_mut() {
                                    opened.edit = None;
                                }
                                cx.notify();
                            },
                        ))),
                )
                .into_any_element();
        }

        let body = text(detail, "body");
        let visibility: Vec<String> = detail["visibility"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|v| v.as_str().map(str::to_string))
            .collect();
        let copy_body = body.clone();
        let description = text(detail, "description");
        panel
            // The row above shows the description unless it was cut short.
            .when(description.chars().count() > DESCRIPTION_CLIP, |col| col.child(ui::muted(description, &theme)))
            .when(!visibility.is_empty(), |col| {
                col.child(
                    div()
                        .text_xs()
                        .text_color(theme.muted_foreground)
                        .child(format!("Visibility: {}", visibility.join(", "))),
                )
            })
            .child(
                v_flex()
                    .rounded_md()
                    .border_1()
                    .border_color(theme.border)
                    .bg(theme.background)
                    .child(
                        h_flex()
                            .justify_between()
                            .px_2()
                            .py_1()
                            .border_b_1()
                            .border_color(theme.border)
                            .child(
                                h_flex()
                                    .gap_1()
                                    .child(
                                        Button::new("view-md")
                                            .xsmall()
                                            .ghost()
                                            .label("Markdown")
                                            .selected(!opened.raw)
                                            .on_click(cx.listener(|this, _, _, cx| {
                                                if let Some(opened) = this.opened.as_mut() {
                                                    opened.raw = false;
                                                }
                                                cx.notify();
                                            })),
                                    )
                                    .child(
                                        Button::new("view-raw")
                                            .xsmall()
                                            .ghost()
                                            .label("Raw")
                                            .selected(opened.raw)
                                            .on_click(cx.listener(|this, _, _, cx| {
                                                if let Some(opened) = this.opened.as_mut() {
                                                    opened.raw = true;
                                                }
                                                cx.notify();
                                            })),
                                    ),
                            )
                            .child(
                                Button::new("copy-body")
                                    .xsmall()
                                    .ghost()
                                    .icon(if opened.copied { IconName::Check } else { IconName::Copy })
                                    .label(if opened.copied { "Copied" } else { "Copy" })
                                    .on_click(cx.listener(move |this, _, _, cx| {
                                        cx.write_to_clipboard(ClipboardItem::new_string(copy_body.clone()));
                                        if let Some(opened) = this.opened.as_mut() {
                                            opened.copied = true;
                                        }
                                        cx.notify();
                                    })),
                            ),
                    )
                    .child(div().p_4().child(if opened.raw {
                        div().text_xs().font_family(theme.mono_font_family.clone()).child(body).into_any_element()
                    } else {
                        ui::markdown(
                            SharedString::from(format!("skill-md:{name}")),
                            strip_frontmatter(&body).to_string(),
                            &theme,
                        )
                        .into_any_element()
                    })),
            )
            .into_any_element()
    }

    fn render_new(&self, form: &NewSkill, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let queen = self
            .queen
            .as_ref()
            .and_then(|id| self.queens.iter().find(|q| &q.id == id))
            .map(|q| q.name.clone())
            .unwrap_or_default();
        let label = |s: &'static str| div().text_xs().font_medium().text_color(theme.muted_foreground).child(s);
        v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(
                v_flex()
                    .child(div().text_sm().font_semibold().child("New skill"))
                    .child(ui::muted(format!("For {queen}."), &theme).text_xs()),
            )
            .child(v_flex().gap_1().child(label("Name")).child(Input::new(&form.name).small()).child(
                ui::muted("Lowercase letters, digits, hyphens and dots; up to 64 characters.", &theme).text_xs(),
            ))
            .child(v_flex().gap_1().child(label("Description")).child(Input::new(&form.description).small()))
            .child(v_flex().gap_1().child(label("Body (SKILL.md)")).child(Textarea::new(&form.body)))
            .when_some(form.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .child(
                h_flex()
                    .gap_2()
                    .justify_end()
                    .child(Button::new("new-cancel").small().ghost().label("Cancel").on_click(cx.listener(
                        |this, _, _, cx| {
                            this.new_skill = None;
                            cx.notify();
                        },
                    )))
                    .child(
                        Button::new("new-create")
                            .small()
                            .primary()
                            .label("Create")
                            .loading(form.saving)
                            .on_click(cx.listener(|this, _, _, cx| this.create(cx))),
                    ),
            )
            .into_any_element()
    }

    fn render_upload(&self, upload: &Upload, cx: &mut Context<Self>) -> AnyElement {
        let page = cx.entity().downgrade();
        let queens: Vec<(String, String)> = self.queens.iter().map(|q| (q.id.clone(), queen_label(q))).collect();
        let target_label = upload
            .target
            .as_ref()
            .and_then(|id| self.queens.iter().find(|q| &q.id == id))
            .map(queen_label)
            .unwrap_or_else(|| "Choose a queen".into());
        let current = upload.target.clone();
        let picker = Button::new("upload-queen")
            .small()
            .outline()
            .label(target_label)
            .dropdown_caret(true)
            .dropdown_menu(move |mut menu, _, _| {
                for (id, label) in &queens {
                    let page = page.clone();
                    let pick = id.clone();
                    menu = menu.item(PopupMenuItem::new(label.clone()).checked(current.as_ref() == Some(id)).on_click(
                        move |_, _, cx| {
                            page.update(cx, |this, cx| {
                                if let Some(upload) = this.upload.as_mut() {
                                    upload.target = Some(pick.clone());
                                }
                                cx.notify();
                            })
                            .ok();
                        },
                    ));
                }
                menu.max_h(px(420.)).scrollable(true)
            });
        let first_queen = self.queens.first().map(|q| q.id.clone());
        let theme = cx.theme().clone();
        let file_line = match &upload.file {
            Some((path, size)) => h_flex()
                .gap_2()
                .child(Icon::new(IconName::FileText).small())
                .child(
                    div()
                        .text_sm()
                        .font_medium()
                        .child(path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()),
                )
                .child(div().text_xs().text_color(theme.muted_foreground).child(size_label(*size))),
            None => ui::muted("No file chosen.", &theme),
        };
        v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(
                v_flex()
                    .child(div().text_sm().font_semibold().child("Upload a skill"))
                    .child(ui::muted("A SKILL.md file or a zipped skill folder, up to 2 MB.", &theme).text_xs()),
            )
            .child(
                h_flex()
                    .gap_3()
                    .child(
                        Button::new("choose-file")
                            .small()
                            .outline()
                            .icon(IconName::Upload)
                            .label("Choose file")
                            .on_click(cx.listener(|this, _, _, cx| this.choose_file(cx))),
                    )
                    .child(file_line),
            )
            .child(
                h_flex()
                    .gap_2()
                    .child(div().text_sm().child("Add to"))
                    .child(
                        Button::new("for-all")
                            .small()
                            .ghost()
                            .label("All queens")
                            .selected(upload.target.is_none())
                            .on_click(cx.listener(|this, _, _, cx| {
                                if let Some(upload) = this.upload.as_mut() {
                                    upload.target = None;
                                }
                                cx.notify();
                            })),
                    )
                    .child(
                        Button::new("for-one")
                            .small()
                            .ghost()
                            .label("One queen")
                            .selected(upload.target.is_some())
                            .on_click(cx.listener(move |this, _, _, cx| {
                                let queen = this.queen.clone().or(first_queen.clone());
                                if let Some(upload) = this.upload.as_mut().filter(|u| u.target.is_none()) {
                                    upload.target = queen;
                                }
                                cx.notify();
                            })),
                    )
                    .when(upload.target.is_some(), |row| row.child(picker)),
            )
            .child(
                h_flex()
                    .gap_2()
                    .child(Switch::new("upload-enabled").checked(upload.enabled).on_click(cx.listener(
                        |this, checked: &bool, _, cx| {
                            if let Some(upload) = this.upload.as_mut() {
                                upload.enabled = *checked;
                            }
                            cx.notify();
                        },
                    )))
                    .child(div().text_sm().child("Turn it on right away")),
            )
            .when_some(upload.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .child(match &upload.conflict {
                Some(conflict) => v_flex()
                    .gap_2()
                    .p_3()
                    .rounded_md()
                    .border_1()
                    .border_color(theme.warning)
                    .child(
                        h_flex()
                            .gap_2()
                            .text_sm()
                            .text_color(theme.warning)
                            .child(Icon::new(IconName::CircleAlert).small())
                            .child(conflict.clone()),
                    )
                    .child(
                        ui::muted("Replace the existing skill with this file? Its contents are overwritten.", &theme)
                            .text_xs(),
                    )
                    .child(
                        h_flex()
                            .gap_2()
                            .justify_end()
                            .child(
                                Button::new("keep-existing")
                                    .small()
                                    .ghost()
                                    .label("Keep existing")
                                    .disabled(upload.uploading)
                                    .on_click(cx.listener(|this, _, _, cx| {
                                        if let Some(upload) = this.upload.as_mut() {
                                            upload.conflict = None;
                                        }
                                        cx.notify();
                                    })),
                            )
                            .child(
                                Button::new("replace")
                                    .small()
                                    .danger()
                                    .label("Replace")
                                    .loading(upload.uploading)
                                    .on_click(cx.listener(|this, _, _, cx| this.upload(true, cx))),
                            ),
                    )
                    .into_any_element(),
                None => h_flex()
                    .gap_2()
                    .justify_end()
                    .child(Button::new("upload-cancel").small().ghost().label("Cancel").on_click(cx.listener(
                        |this, _, _, cx| {
                            this.upload = None;
                            cx.notify();
                        },
                    )))
                    .child(
                        Button::new("upload-go")
                            .small()
                            .primary()
                            .label("Upload")
                            .loading(upload.uploading)
                            .disabled(upload.file.is_none())
                            .on_click(cx.listener(|this, _, _, cx| this.upload(false, cx))),
                    )
                    .into_any_element(),
            })
            .into_any_element()
    }

    fn render_sources(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let sources = &self.sources;
        let paths = self.source_paths();
        let summary = match &sources.loaded {
            None => "loading…".to_string(),
            Some(Err(_)) => "couldn't load".to_string(),
            Some(Ok(_)) if paths.is_empty() => "none yet; import skills from Claude Code, Codex and others".to_string(),
            Some(Ok(v)) => {
                let skills: i64 =
                    v["resolved"].as_array().into_iter().flatten().map(|r| r["skills"].as_i64().unwrap_or(0)).sum();
                format!("{} {} · {skills} skills", paths.len(), if paths.len() == 1 { "folder" } else { "folders" })
            }
        };
        let header = h_flex()
            .id("sources-toggle")
            .gap_2()
            .cursor_pointer()
            .child(Icon::new(IconName::FolderInput).small())
            .child(div().text_sm().font_medium().child("External skill sources"))
            .child(div().text_xs().text_color(theme.muted_foreground).child(summary))
            .child(div().flex_1())
            .child(Icon::new(if sources.open { IconName::ChevronUp } else { IconName::ChevronDown }).small())
            .on_click(cx.listener(|this, _, _, cx| {
                this.sources.open = !this.sources.open;
                cx.notify();
            }));
        let mut panel = v_flex().gap_2().px_4().py_3().rounded_lg().border_1().border_color(theme.border).child(header);
        if !sources.open {
            return panel.into_any_element();
        }
        if let Some(Err(e)) = &sources.loaded {
            panel = panel.child(ui::error_line(format!("Couldn't load the sources: {e}"), &theme));
        }
        let loaded = match &sources.loaded {
            Some(Ok(v)) => v.clone(),
            _ => Value::Null,
        };
        for (ix, r) in loaded["resolved"].as_array().cloned().unwrap_or_default().into_iter().enumerate() {
            let path = text(&r, "path");
            let confirming = sources.confirm_remove.as_deref() == Some(path.as_str());
            let status = if flag(&r, "exists") {
                let n = r["skills"].as_i64().unwrap_or(0);
                let resolved = text(&r, "resolved");
                h_flex()
                    .gap_1()
                    .text_xs()
                    .text_color(theme.muted_foreground)
                    .child(Icon::new(IconName::Check).xsmall().text_color(theme.success))
                    .child(format!(
                        "{n} {} found{}",
                        if n == 1 { "skill" } else { "skills" },
                        if resolved.is_empty() { String::new() } else { format!(" · {resolved}") }
                    ))
            } else {
                let problem =
                    Some(text(&r, "error")).filter(|e| !e.is_empty()).unwrap_or_else(|| "Folder not found".into());
                h_flex()
                    .gap_1()
                    .text_xs()
                    .text_color(theme.warning)
                    .child(Icon::new(IconName::CircleAlert).xsmall())
                    .child(problem)
            };
            panel = panel.child(
                h_flex()
                    .gap_2()
                    .px_3()
                    .py_2()
                    .rounded_md()
                    .border_1()
                    .border_color(theme.border)
                    .bg(theme.background)
                    .child(
                        v_flex()
                            .flex_1()
                            .min_w_0()
                            .child(
                                div()
                                    .text_sm()
                                    .font_family(theme.mono_font_family.clone())
                                    .truncate()
                                    .child(path.clone()),
                            )
                            .child(status),
                    )
                    .child(
                        Button::new(("remove-source", ix))
                            .small()
                            .ghost()
                            .disabled(sources.saving)
                            .when(confirming, |b| b.danger().label("Remove this source"))
                            .when(!confirming, |b| b.icon(IconName::X).tooltip("Remove"))
                            .on_click(cx.listener(move |this, _, _, cx| {
                                if this.sources.confirm_remove.as_deref() == Some(path.as_str()) {
                                    let paths = this.source_paths().into_iter().filter(|p| *p != path).collect();
                                    this.save_sources(paths, cx);
                                } else {
                                    this.sources.confirm_remove = Some(path.clone());
                                    cx.notify();
                                }
                            })),
                    ),
            );
        }
        panel = panel.child(
            h_flex().gap_2().child(div().flex_1().child(Input::new(&sources.draft).small())).child(
                Button::new("add-source")
                    .small()
                    .outline()
                    .icon(IconName::Plus)
                    .label("Add")
                    .loading(sources.saving)
                    .on_click(cx.listener(|this, _, window, cx| this.add_source(window, cx))),
            ),
        );
        let suggestions = loaded["suggestions"].as_array().cloned().unwrap_or_default();
        if !suggestions.is_empty() {
            panel = panel.child(
                h_flex()
                    .gap_2()
                    .flex_wrap()
                    .child(div().text_xs().text_color(theme.muted_foreground).child("Found on this computer:"))
                    .children(suggestions.into_iter().enumerate().map(|(ix, s)| {
                        let path = text(&s, "path");
                        Button::new(("suggestion", ix))
                            .xsmall()
                            .outline()
                            .icon(IconName::Plus)
                            .label(format!("{path} · {}", s["skills"].as_i64().unwrap_or(0)))
                            .tooltip(text(&s, "resolved"))
                            .disabled(sources.saving)
                            .on_click(cx.listener(move |this, _, _, cx| {
                                let mut paths = this.source_paths();
                                if !paths.contains(&path) {
                                    paths.push(path.clone());
                                    this.save_sources(paths, cx);
                                }
                            }))
                    })),
            );
        }
        if let Some(e) = &sources.error {
            panel = panel.child(ui::error_line(e.clone(), &theme));
        }
        panel.into_any_element()
    }
}

/// "Name · Role", which tells apart two queens of the same name.
fn queen_label(queen: &Queen) -> String {
    let role = ui::role(&queen.title);
    if role.is_empty() { queen.name.clone() } else { format!("{} · {role}", queen.name) }
}

impl Render for SkillsPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) =
            ui::page("skills-body", "Skills", "Every skill the queens can use. Pick a queen to choose hers.", &theme);
        let library = match &self.library {
            None => return v_flex().size_full().child(header).child(body.child(v_flex().p_8().child(Spinner::new()))),
            Some(Err(e)) => {
                return v_flex().size_full().child(header).child(
                    body.child(v_flex().p_8().child(ui::error_line(format!("Couldn't load skills: {e}"), &theme))),
                );
            }
            Some(Ok(library)) => library.clone(),
        };

        let picker = self.render_queen_picker(cx);
        let toolbar = h_flex()
            .gap_2()
            .child(picker)
            .child(div().w(px(280.)).child(Input::new(&self.search).small()))
            .child(div().flex_1())
            .when(self.queen.is_some(), |row| {
                row.child(
                    Button::new("new-skill")
                        .small()
                        .primary()
                        .icon(IconName::Plus)
                        .label("New")
                        .selected(self.new_skill.is_some())
                        .on_click(cx.listener(|this, _, window, cx| this.toggle_new(window, cx))),
                )
            })
            .child(
                Button::new("upload-skill")
                    .small()
                    .outline()
                    .icon(IconName::Upload)
                    .label("Upload")
                    .selected(self.upload.is_some())
                    .on_click(cx.listener(|this, _, _, cx| this.toggle_upload(cx))),
            )
            .child(Button::new("refresh").small().ghost().icon(IconName::RefreshCw).tooltip("Refresh").on_click(
                cx.listener(|this, _, _, cx| {
                    this.load(cx);
                    this.load_sources(cx);
                }),
            ));

        let new_form = self.new_skill.as_ref().map(|form| self.render_new(form, cx));
        let upload_form = self.upload.as_ref().map(|upload| self.render_upload(upload, cx));
        let sources = self.render_sources(cx);

        let query = self.search.read(cx).value().to_lowercase();
        let picked = self.queen.is_some();
        let all_rows: Option<Vec<Value>> =
            if picked { self.rows.clone() } else { library["skills"].as_array().cloned() };
        let list: AnyElement = match all_rows {
            None => Spinner::new().into_any_element(),
            Some(all_rows) => {
                let shown: Vec<Value> = all_rows
                    .into_iter()
                    .filter(|r| {
                        query.is_empty()
                            || text(r, "name").to_lowercase().contains(&query)
                            || text(r, "description").to_lowercase().contains(&query)
                    })
                    // The open skill stays put when it's switched, so the switch doesn't whisk it away.
                    .filter(|r| {
                        !picked
                            || flag(r, "enabled") != self.show_inactive
                            || self.opened.as_ref().is_some_and(|o| o.name == text(r, "name"))
                    })
                    .collect();
                let mut rows = Vec::new();
                for (ix, r) in shown.iter().enumerate() {
                    let name = text(r, "name");
                    let enabled = flag(r, "enabled");
                    let used_by = r["visible_to"]["queens"].as_array().map(|q| q.len());
                    let owner = text(&r["owner"], "id");
                    let open_name = name.clone();
                    let mut item = v_flex().gap_2().child(
                        ui::card(&theme)
                            .id(("skill", ix))
                            .cursor_pointer()
                            .hover(|row| row.bg(theme.list_hover))
                            .when(picked, |row| {
                                row.child(ui::dot(if enabled { theme.success } else { theme.muted_foreground }))
                            })
                            .child(
                                v_flex()
                                    .min_w_0()
                                    .flex_1()
                                    .child(
                                        h_flex()
                                            .gap_2()
                                            .child(div().text_sm().font_medium().truncate().child(name.clone()))
                                            .when(!flag(r, "editable"), |row| {
                                                row.child(
                                                    Icon::new(IconName::Lock)
                                                        .xsmall()
                                                        .text_color(theme.muted_foreground),
                                                )
                                            })
                                            .when(!owner.is_empty(), |row| {
                                                row.child(
                                                    div()
                                                        .text_xs()
                                                        .text_color(theme.muted_foreground)
                                                        .child(format!("@{owner}")),
                                                )
                                            }),
                                    )
                                    .child(
                                        div()
                                            .text_sm()
                                            .text_color(theme.muted_foreground)
                                            .child(ui::clip(&text(r, "description"), DESCRIPTION_CLIP)),
                                    ),
                            )
                            .child(div().flex_shrink_0().text_xs().text_color(theme.muted_foreground).child(
                                match (picked, used_by) {
                                    (true, _) => (if enabled { "Active" } else { "Inactive" }).to_string(),
                                    (false, Some(n)) => {
                                        format!("Used by {n} {}", if n == 1 { "queen" } else { "queens" })
                                    }
                                    (false, None) => String::new(),
                                },
                            ))
                            .on_click(cx.listener(move |this, _, _, cx| this.open(open_name.clone(), cx))),
                    );
                    if let Some(opened) = self.opened.as_ref().filter(|o| o.name == name) {
                        item = item.child(self.render_opened(opened, Some(r), cx));
                    }
                    rows.push(item.into_any_element());
                }
                if rows.is_empty() {
                    ui::muted(if picked { "No skills match." } else { "No skills on this machine yet." }, &theme)
                        .into_any_element()
                } else {
                    v_flex().gap_2().children(rows).into_any_element()
                }
            }
        };

        let content = v_flex()
            .gap_4()
            .px_8()
            .py_6()
            .w_full()
            .max_w(px(880.))
            .mx_auto()
            .child(toolbar)
            .children(new_form)
            .children(upload_form)
            .child(sources)
            .when(picked, |col| {
                col.child(
                    h_flex()
                        .gap_1()
                        .child(
                            Button::new("show-active")
                                .small()
                                .ghost()
                                .label("Active")
                                .selected(!self.show_inactive)
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.show_inactive = false;
                                    cx.notify();
                                })),
                        )
                        .child(
                            Button::new("show-inactive")
                                .small()
                                .ghost()
                                .label("Inactive")
                                .selected(self.show_inactive)
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.show_inactive = true;
                                    cx.notify();
                                })),
                        ),
                )
            })
            .child(list);
        v_flex().size_full().child(header).child(body.child(content))
    }
}

#[cfg(test)]
mod tests {
    // Not a glob: `gpui_kit::*` brings a `test` attribute of its own.
    use super::{is_upload, strip_frontmatter};

    #[test]
    fn frontmatter_is_stripped() {
        assert_eq!(strip_frontmatter("---\nname: ava\ndescription: x\n---\n## Steps\n"), "## Steps\n");
        assert_eq!(strip_frontmatter("\n---\r\nname: ivy\r\n---\r\nbody"), "body");
        assert_eq!(strip_frontmatter("## No header\n---\n"), "## No header\n---\n");
        assert_eq!(strip_frontmatter("---\nnever closed\n"), "---\nnever closed\n");
    }

    #[test]
    fn only_md_and_zip_upload() {
        assert!(is_upload(std::path::Path::new("SKILL.md")));
        assert!(is_upload(std::path::Path::new("bundle.ZIP")));
        assert!(!is_upload(std::path::Path::new("notes.txt")));
    }
}
