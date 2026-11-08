//! The window's frame: the sidebar (pages, colonies, queens) and whatever it has open.

use std::collections::HashMap;

use gpui_kit::assets::IconName;
use gpui_kit::base::{h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputEvent, InputState, Textarea, TextareaState};
use gpui_kit::component::menu::{DropdownMenu as _, PopupMenuItem};
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use crate::api::{Queen, api};
use crate::chat_view::{ChatEvent, ChatView, Target};
use crate::colony_view::ColonyView;
use crate::live::{Live, State};
use crate::{avatars, bg, pages, ui};

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Page {
    Home,
    OrgChart,
    Models,
    Credentials,
    Skills,
    Tools,
    Prompts,
    Memory,
    Settings,
}

impl Page {
    const ALL: [Page; 9] = [
        Page::Home,
        Page::OrgChart,
        Page::Models,
        Page::Credentials,
        Page::Skills,
        Page::Tools,
        Page::Prompts,
        Page::Memory,
        Page::Settings,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Page::Home => "Home",
            Page::OrgChart => "Org chart",
            Page::Models => "Models",
            Page::Credentials => "Credentials",
            Page::Skills => "Skills",
            Page::Tools => "Tools",
            Page::Prompts => "Prompts",
            Page::Memory => "Memory",
            Page::Settings => "Settings",
        }
    }

    fn icon(self) -> IconName {
        match self {
            Page::Home => IconName::House,
            Page::OrgChart => IconName::Network,
            Page::Models => IconName::Cpu,
            Page::Credentials => IconName::KeyRound,
            Page::Skills => IconName::Sparkles,
            Page::Tools => IconName::Wrench,
            Page::Prompts => IconName::MessageSquareText,
            Page::Memory => IconName::Brain,
            Page::Settings => IconName::Settings,
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub enum Route {
    Page(Page),
    /// A direct chat with the queen of this id.
    Queen(String),
    /// The queen's profile page.
    Profile(String),
    /// The colony with this directory name.
    Colony(String),
    /// A queen that runs on Claude Code, by id; read only.
    ClaudeCode(String),
}

impl Route {
    /// `models`, `org-chart`, …, `queen:<id>`, `profile:<id>` or `colony:<name>`, as `--open` takes it.
    pub fn parse(s: &str) -> Option<Route> {
        if let Some(id) = s.strip_prefix("queen:") {
            return Some(Route::Queen(id.to_string()));
        }
        if let Some(id) = s.strip_prefix("profile:") {
            return Some(Route::Profile(id.to_string()));
        }
        if let Some(name) = s.strip_prefix("colony:") {
            return Some(Route::Colony(name.to_string()));
        }
        if let Some(id) = s.strip_prefix("claude-code:") {
            return Some(Route::ClaudeCode(id.to_string()));
        }
        Page::ALL.into_iter().find(|p| p.label().to_lowercase().replace(' ', "-") == s).map(Route::Page)
    }

    /// The route as [`Route::parse`] reads it.
    pub fn key(&self) -> String {
        match self {
            Route::Page(page) => page.label().to_lowercase().replace(' ', "-"),
            Route::Queen(id) => format!("queen:{id}"),
            Route::Profile(id) => format!("profile:{id}"),
            Route::Colony(name) => format!("colony:{name}"),
            Route::ClaudeCode(id) => format!("claude-code:{id}"),
        }
    }
}

/// A colony as the sidebar lists it.
#[derive(Clone)]
pub struct Colony {
    /// Its directory name, which every colony API takes.
    pub name: String,
    pub label: String,
}

/// The colonies `GET /discover` lists under "Your Agents"; the directory name ends the path.
fn colonies_of(discover: &Value) -> Vec<Colony> {
    let mut colonies: Vec<Colony> = discover["Your Agents"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|entry| {
            let path = entry["path"].as_str()?;
            let name = path.trim_end_matches(['/', '\\']).rsplit(['/', '\\']).next()?.to_string();
            let label = entry["name"]
                .as_str()
                .filter(|n| !n.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| name.replace('_', " "));
            Some(Colony { name, label })
        })
        .collect();
    colonies.sort_by_key(|c| c.label.to_lowercase());
    colonies
}

fn state_color(state: Option<State>, theme: &Theme) -> Option<Hsla> {
    match state? {
        State::Working => Some(theme.success),
        State::Waiting => Some(theme.warning),
        State::Idle => Some(theme.muted_foreground),
    }
}

actions!(shell, [OpenSwitcher, CloseSwitcher]);

/// The quick switcher: a search over every queen, colony and page.
struct Switcher {
    query: Entity<InputState>,
}

/// One place the switcher can go: what it's called, what kind of place it is, and where it goes.
struct Place {
    label: String,
    kind: &'static str,
    route: Route,
}

/// The palette's places matching `query` (any order of words, ignoring case), queens first.
fn places_matching(query: &str, queens: &[Queen], colonies: &[Colony], claude_code: &[(String, String)]) -> Vec<Place> {
    let words: Vec<String> = query.split_whitespace().map(str::to_lowercase).collect();
    let fits = |label: &str| {
        let label = label.to_lowercase();
        words.iter().all(|w| label.contains(w.as_str()))
    };
    let mut places = Vec::new();
    for q in queens {
        let label = format!("{} · {}", q.name, ui::role(&q.title));
        if fits(&label) {
            places.push(Place { label, kind: "Chat", route: Route::Queen(q.id.clone()) });
        }
    }
    for c in colonies.iter().filter(|c| fits(&c.label)) {
        places.push(Place { label: c.label.clone(), kind: "Colony", route: Route::Colony(c.name.clone()) });
    }
    for (id, name) in claude_code.iter().filter(|(_, name)| fits(name)) {
        places.push(Place { label: name.clone(), kind: "Claude Code", route: Route::ClaudeCode(id.clone()) });
    }
    for page in Page::ALL.into_iter().filter(|p| fits(p.label())) {
        places.push(Place { label: page.label().to_string(), kind: "Page", route: Route::Page(page) });
    }
    for q in queens {
        let label = format!("{} · profile", q.name);
        if !words.is_empty() && fits(&label) {
            places.push(Place { label, kind: "Profile", route: Route::Profile(q.id.clone()) });
        }
    }
    places
}

/// The sidebar's "new colony" form.
struct NewColony {
    name: Entity<InputState>,
    goal: Entity<TextareaState>,
    queen: Option<String>,
    error: Option<String>,
    working: bool,
}

/// What a typed colony name becomes: lowercase letters, digits and `_`, as the server takes it.
fn colony_slug(name: &str) -> String {
    name.trim()
        .to_lowercase()
        .chars()
        .map(|c| if c.is_whitespace() || c == '-' { '_' } else { c })
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '_')
        .collect()
}

pub struct Shell {
    queens: Vec<Queen>,
    queens_error: Option<String>,
    colonies: Vec<Colony>,
    live: Entity<Live>,
    route: Route,
    /// Where to go once the queens are known, for a start-up `--open queen:<id>`.
    pending: Option<Route>,
    /// One chat per queen visited, kept so switching back keeps the draft and the stream.
    chats: HashMap<String, Entity<ChatView>>,
    pages: HashMap<Page, AnyView>,
    /// Profile pages by queen id, colony views by colony name.
    profiles: HashMap<String, AnyView>,
    colony_views: HashMap<String, Entity<ColonyView>>,
    claude_code: HashMap<String, AnyView>,
    /// Queens that run on Claude Code: (id, name).
    claude_code_queens: Vec<(String, String)>,
    new_colony: Option<NewColony>,
    switcher: Option<Switcher>,
    /// Saves the window's place once it stops moving.
    save_bounds: Option<Task<()>>,
    tasks: Vec<Task<()>>,
}

impl Shell {
    pub fn new(open: Option<Route>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let live = cx.new(Live::new);
        cx.observe(&live, |_, _, cx| cx.notify()).detach();
        let mut shell = Self {
            queens: Vec::new(),
            queens_error: None,
            colonies: Vec::new(),
            live,
            route: Route::Page(Page::Home),
            pending: None,
            chats: HashMap::new(),
            pages: HashMap::new(),
            profiles: HashMap::new(),
            colony_views: HashMap::new(),
            claude_code: HashMap::new(),
            claude_code_queens: Vec::new(),
            new_colony: None,
            switcher: None,
            save_bounds: None,
            tasks: Vec::new(),
        };
        cx.observe_window_bounds(window, |this, window, cx| {
            let bounds = window.window_bounds();
            // Dragging moves the window many times a second; only the place it comes to rest is kept.
            this.save_bounds = Some(cx.spawn(async move |_, cx| {
                cx.background_executor().timer(std::time::Duration::from_millis(500)).await;
                crate::state::update(|s| s.window = crate::state::SavedBounds::of(bounds));
            }));
        })
        .detach();
        match open {
            Some(Route::Queen(id)) => {
                shell.pending = Some(Route::Queen(id));
                shell.go(Route::Page(Page::Home), window, cx);
            }
            Some(route) => shell.go(route, window, cx),
            None => shell.go(Route::Page(Page::Home), window, cx),
        }
        shell.load_queens(window, cx);
        shell.load_colonies(cx);
        shell.load_claude_code(cx);
        shell
    }

    pub fn queens(&self) -> &[Queen] {
        &self.queens
    }

    fn load_queens(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.queens(),
            |this: &mut Self, loaded, window, cx| match loaded {
                Ok(queens) => {
                    this.queens = queens;
                    this.queens_error = None;
                    if let Some(route) = this.pending.take() {
                        this.go(route, window, cx);
                    }
                }
                Err(e) => this.queens_error = Some(format!("Can't reach Hive: {e}")),
            },
        ));
    }

    fn load_claude_code(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/claude-code-queens"),
            |this: &mut Self, found, _| {
                if let Ok(body) = found {
                    this.claude_code_queens = body["queens"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|q| {
                            Some((q["id"].as_str()?.to_string(), q["name"].as_str().unwrap_or_default().to_string()))
                        })
                        .collect();
                }
            },
        ));
    }

    /// Reload the colony list, e.g. after one was created.
    pub fn load_colonies(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/discover"),
            |this: &mut Self, found, _| {
                if let Ok(discover) = found {
                    this.colonies = colonies_of(&discover);
                }
            },
        ));
    }

    pub fn go(&mut self, route: Route, window: &mut Window, cx: &mut Context<Self>) {
        match &route {
            Route::Queen(id) => {
                let Some(queen) = self.queens.iter().find(|q| &q.id == id).cloned() else { return };
                let chat = match self.chats.get(id) {
                    Some(chat) => chat.clone(),
                    None => {
                        let chat = cx.new(|cx| ChatView::new(Target::Queen(queen), window, cx));
                        cx.subscribe_in(&chat, window, Self::on_chat_event).detach();
                        self.chats.insert(id.clone(), chat.clone());
                        chat
                    }
                };
                chat.update(cx, |chat, cx| chat.focus(window, cx));
            }
            Route::Page(page) => {
                if !self.pages.contains_key(page) {
                    let view = pages::build(*page, cx.entity().downgrade(), window, cx);
                    self.pages.insert(*page, view);
                }
            }
            Route::Profile(id) => {
                if !self.profiles.contains_key(id) {
                    let view = pages::profile(id.clone(), cx.entity().downgrade(), window, cx);
                    self.profiles.insert(id.clone(), view);
                }
            }
            Route::ClaudeCode(id) => {
                if !self.claude_code.contains_key(id) {
                    let view = pages::claude_code(id.clone(), window, cx);
                    self.claude_code.insert(id.clone(), view);
                }
            }
            Route::Colony(name) => {
                if !self.colony_views.contains_key(name) {
                    let view = cx.new(|cx| ColonyView::new(name.clone(), window, cx));
                    cx.subscribe_in(&view, window, Self::on_chat_event).detach();
                    self.colony_views.insert(name.clone(), view);
                    // A colony opened here may be new to the sidebar.
                    if !self.colonies.iter().any(|c| &c.name == name) {
                        self.load_colonies(cx);
                    }
                }
            }
        }
        let (key, server) = (route.key(), api(cx).base().to_string());
        crate::state::update(|s| {
            s.route = Some(key);
            s.server = Some(server);
        });
        self.route = route;
        cx.notify();
    }

    fn on_chat_event<V>(&mut self, _: &Entity<V>, event: &ChatEvent, window: &mut Window, cx: &mut Context<Self>) {
        match event {
            ChatEvent::Go(route) => {
                // A colony started from a chat is new to the sidebar.
                if let Route::Colony(name) = route
                    && !self.colonies.iter().any(|c| &c.name == name)
                {
                    self.load_colonies(cx);
                }
                self.go(route.clone(), window, cx);
            }
            ChatEvent::ColonyChanged { forget, go } => {
                self.forget(&Route::Colony(forget.clone()));
                self.load_colonies(cx);
                self.go(go.clone(), window, cx);
            }
            _ => {}
        }
    }

    fn open_switcher(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let query = cx.new(|cx| InputState::new(window, cx).placeholder("Go to a queen, colony or page…"));
        cx.observe(&query, |_, _, cx| cx.notify()).detach();
        cx.subscribe_in(&query, window, |this, _, event: &InputEvent, window, cx| {
            if let InputEvent::PressEnter { .. } = event {
                let first = this.switcher_places(cx).into_iter().next();
                if let Some(place) = first {
                    this.switcher = None;
                    this.go(place.route, window, cx);
                }
            }
        })
        .detach();
        query.update(cx, |s, cx| s.focus(window, cx));
        self.switcher = Some(Switcher { query });
        cx.notify();
    }

    fn switcher_places(&self, cx: &App) -> Vec<Place> {
        let query = self.switcher.as_ref().map(|s| s.query.read(cx).value().to_string()).unwrap_or_default();
        places_matching(&query, &self.queens, &self.colonies, &self.claude_code_queens)
    }

    fn render_switcher(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        let switcher = self.switcher.as_ref()?;
        let places = self.switcher_places(cx);
        let rows: Vec<AnyElement> = places
            .into_iter()
            .take(12)
            .enumerate()
            .map(|(ix, place)| {
                let theme = cx.theme();
                let route = place.route.clone();
                h_flex()
                    .id(("place", ix))
                    .justify_between()
                    .px_3()
                    .py_1p5()
                    .rounded_md()
                    .cursor_pointer()
                    .when(ix == 0, |row| row.bg(theme.list_active))
                    .hover(|row| row.bg(theme.list_hover))
                    .child(div().text_sm().truncate().child(place.label))
                    .child(div().text_xs().text_color(theme.muted_foreground).child(place.kind))
                    .on_click(cx.listener(move |this, _, window, cx| {
                        this.switcher = None;
                        this.go(route.clone(), window, cx);
                    }))
                    .into_any_element()
            })
            .collect();
        let close = cx.listener(|this, _: &MouseDownEvent, _, cx| {
            this.switcher = None;
            cx.notify();
        });
        let theme = cx.theme();
        Some(
            div()
                .absolute()
                .size_full()
                .flex()
                .justify_center()
                // Without this the palette stretches to its full height however few places match.
                .items_start()
                .pt(px(96.))
                .bg(theme.overlay)
                .occlude()
                .on_mouse_down(MouseButton::Left, close)
                .child(
                    v_flex()
                        .id("switcher")
                        .key_context("Switcher")
                        .w(px(560.))
                        .max_h(px(480.))
                        .gap_1()
                        .p_2()
                        .rounded_lg()
                        .border_1()
                        .border_color(theme.border)
                        .bg(theme.background)
                        .shadow_lg()
                        // Clicks inside the palette don't count as clicking away from it.
                        .on_mouse_down(MouseButton::Left, |_, _, cx| cx.stop_propagation())
                        .child(Input::new(&switcher.query))
                        .children(rows)
                        .child(
                            div()
                                .px_3()
                                .pt_1()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child("Enter opens the first match · Esc closes"),
                        ),
                )
                .into_any_element(),
        )
    }

    fn toggle_new_colony(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.new_colony.take().is_none() {
            let name = cx.new(|cx| InputState::new(window, cx).placeholder("colony_name"));
            let goal = cx.new(|cx| {
                TextareaState::new(window, cx).auto_grow(2, 6).placeholder("What should it work on? (optional)")
            });
            name.update(cx, |s, cx| s.focus(window, cx));
            self.new_colony = Some(NewColony { name, goal, queen: None, error: None, working: false });
        }
        cx.notify();
    }

    fn create_colony(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(form) = self.new_colony.as_mut() else { return };
        let slug = colony_slug(&form.name.read(cx).value());
        let goal = form.goal.read(cx).value().trim().to_string();
        let Some(queen) = form.queen.clone() else {
            form.error = Some("Pick the queen who leads it.".into());
            cx.notify();
            return;
        };
        if slug.is_empty() {
            form.error = Some("Give it a name.".into());
            cx.notify();
            return;
        }
        form.working = true;
        let api = api(cx);
        let mut body = json!({ "colony_id": slug, "queen_name": queen, "initial_phase": "colony" });
        if !goal.is_empty() {
            body["initial_prompt"] = json!(goal);
        }
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.post("/sessions", body),
            move |this: &mut Self, created, window, cx| match created {
                Ok(created) => {
                    this.new_colony = None;
                    this.load_colonies(cx);
                    // The server's id, which may differ from the typed name.
                    let colony = created["colony_id"].as_str().filter(|id| !id.is_empty()).unwrap_or(&slug);
                    this.go(Route::Colony(colony.to_string()), window, cx);
                }
                Err(e) => {
                    if let Some(form) = this.new_colony.as_mut() {
                        form.working = false;
                        form.error = Some(e.to_string());
                    }
                }
            },
        ));
        cx.notify();
    }

    fn render_new_colony(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        let form = self.new_colony.as_ref()?;
        let shell = cx.entity().downgrade();
        let queens: Vec<(String, String)> = self.queens.iter().map(|q| (q.id.clone(), q.name.clone())).collect();
        let picked = form.queen.clone();
        let label = picked
            .as_ref()
            .and_then(|id| self.queens.iter().find(|q| &q.id == id))
            .map(|q| format!("Led by {}", q.name))
            .unwrap_or_else(|| "Pick a queen".into());
        let picker = Button::new("new-colony-queen").small().outline().label(label).dropdown_caret(true).dropdown_menu(
            move |mut menu, _, _| {
                for (id, name) in &queens {
                    let (shell, id2) = (shell.clone(), id.clone());
                    menu = menu.item(PopupMenuItem::new(name.clone()).checked(picked.as_ref() == Some(id)).on_click(
                        move |_, _, cx| {
                            shell
                                .update(cx, |this, cx| {
                                    if let Some(form) = this.new_colony.as_mut() {
                                        form.queen = Some(id2.clone());
                                    }
                                    cx.notify();
                                })
                                .ok();
                        },
                    ));
                }
                menu.max_h(px(360.)).scrollable(true)
            },
        );
        let create = cx.listener(|this, _, window, cx| this.create_colony(window, cx));
        let theme = cx.theme();
        Some(
            v_flex()
                .gap_2()
                .mx_1()
                .p_2()
                .rounded_md()
                .border_1()
                .border_color(theme.border)
                .bg(theme.background)
                .child(Input::new(&form.name).small())
                .child(picker)
                .child(Textarea::new(&form.goal))
                .when_some(form.error.clone(), |c, e| c.child(ui::error_line(e, theme)))
                .child(
                    h_flex().justify_end().child(
                        Button::new("create-colony")
                            .small()
                            .primary()
                            .label("Create")
                            .loading(form.working)
                            .on_click(create),
                    ),
                )
                .into_any_element(),
        )
    }

    /// Open the queen's chat and send `message` there, in a new chat if `fresh` (as the web's
    /// `?new=1` does for the home composer and the prompt library).
    pub fn chat_with(
        &mut self,
        queen_id: &str,
        message: String,
        fresh: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.go(Route::Queen(queen_id.to_string()), window, cx);
        if let Some(chat) = self.chats.get(queen_id).cloned() {
            chat.update(cx, |chat, cx| chat.send_soon(message, fresh, window, cx));
        }
    }

    /// Forget a cached view so the next visit builds it afresh, e.g. after a queen is renamed.
    pub fn forget(&mut self, route: &Route) {
        match route {
            Route::Page(page) => drop(self.pages.remove(page)),
            Route::Queen(id) => drop(self.chats.remove(id)),
            Route::Profile(id) => drop(self.profiles.remove(id)),
            Route::Colony(name) => drop(self.colony_views.remove(name)),
            Route::ClaudeCode(id) => drop(self.claude_code.remove(id)),
        }
    }

    /// Reload the queen list, e.g. after one was created, renamed, removed or given a new picture.
    pub fn refresh_queens(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        avatars::forget_all(cx);
        self.load_queens(window, cx);
    }

    fn render_sidebar(&self, cx: &mut Context<Self>) -> impl IntoElement {
        // The web sidebar's 13 px rows.
        let row_text = px(13.);
        let nav: Vec<AnyElement> = Page::ALL
            .iter()
            .map(|&page| {
                let active = self.route == Route::Page(page);
                let theme = cx.theme();
                h_flex()
                    .id(page.label())
                    .gap_2p5()
                    .px_2()
                    .py_1()
                    .rounded_md()
                    .cursor_pointer()
                    .text_size(row_text)
                    .when(active, |row| row.bg(theme.list_active).text_color(theme.foreground))
                    .when(!active, |row| row.text_color(theme.sidebar_foreground).hover(|row| row.bg(theme.list_hover)))
                    .child(Icon::new(page.icon()).small().text_color(if active {
                        theme.primary
                    } else {
                        theme.muted_foreground
                    }))
                    .child(page.label())
                    .on_click(cx.listener(move |this, _, window, cx| this.go(Route::Page(page), window, cx)))
                    .into_any_element()
            })
            .collect();
        let live = self.live.read(cx);
        let colony_states: Vec<Option<State>> = self.colonies.iter().map(|c| live.colony(&c.name)).collect();
        let queen_states: Vec<Option<State>> = self.queens.iter().map(|q| live.queen(&q.id)).collect();
        let colonies: Vec<AnyElement> = self
            .colonies
            .iter()
            .zip(colony_states)
            .enumerate()
            .map(|(ix, (colony, state))| {
                let active = self.route == Route::Colony(colony.name.clone());
                let theme = cx.theme();
                let name = colony.name.clone();
                h_flex()
                    .id(("colony", ix))
                    .gap_2p5()
                    .px_2()
                    .py_1()
                    .rounded_md()
                    .cursor_pointer()
                    .text_size(row_text)
                    .when(active, |row| row.bg(theme.list_active))
                    .when(!active, |row| row.hover(|row| row.bg(theme.list_hover)))
                    // Idle colonies get a quiet ring; working or waiting ones the state's color, as on the web.
                    .child(match state_color(state, theme) {
                        Some(color) => ui::dot(color).into_any_element(),
                        None => div()
                            .size(px(8.))
                            .flex_shrink_0()
                            .rounded_full()
                            .border_1()
                            .border_color(theme.muted_foreground)
                            .into_any_element(),
                    })
                    .child(div().flex_1().min_w_0().truncate().child(colony.label.clone()))
                    .on_click(cx.listener(move |this, _, window, cx| this.go(Route::Colony(name.clone()), window, cx)))
                    .into_any_element()
            })
            .collect();
        let queens: Vec<AnyElement> = self
            .queens
            .clone()
            .into_iter()
            .zip(queen_states)
            .enumerate()
            .map(|(ix, (queen, state))| {
                let active = self.route == Route::Queen(queen.id.clone());
                let picture = avatars::avatar(&queen, px(24.), cx);
                let theme = cx.theme();
                let title = ui::role(&queen.title).to_string();
                let id = queen.id.clone();
                let dot = state_color(state, theme);
                h_flex()
                    .id(("queen", ix))
                    .gap_2p5()
                    .px_2()
                    .py_1()
                    .rounded_md()
                    .cursor_pointer()
                    .when(active, |row| row.bg(theme.list_active))
                    .when(!active, |row| row.hover(|row| row.bg(theme.list_hover)))
                    // Her state as a dot on her picture's corner, as the web sidebar shows it.
                    .child(div().relative().flex_shrink_0().child(picture).when_some(dot, |pic, color| {
                        pic.child(
                            div()
                                .absolute()
                                .right(px(-2.))
                                .bottom(px(-2.))
                                .size(px(10.))
                                .rounded_full()
                                .bg(color)
                                .border_2()
                                .border_color(theme.sidebar),
                        )
                    }))
                    .child(
                        h_flex()
                            .flex_1()
                            .min_w_0()
                            .gap_1p5()
                            .items_baseline()
                            .child(
                                div()
                                    .flex_shrink_0()
                                    .text_size(row_text)
                                    .text_color(theme.foreground)
                                    .child(queen.name.clone()),
                            )
                            .when(!title.is_empty(), |row| {
                                row.child(
                                    div()
                                        .min_w_0()
                                        .truncate()
                                        .text_xs()
                                        .text_color(theme.muted_foreground)
                                        .child(title),
                                )
                            }),
                    )
                    .on_click(cx.listener(move |this, _, window, cx| this.go(Route::Queen(id.clone()), window, cx)))
                    .into_any_element()
            })
            .collect();
        let claude_code: Vec<AnyElement> = self
            .claude_code_queens
            .iter()
            .enumerate()
            .map(|(ix, (id, name))| {
                let active = self.route == Route::ClaudeCode(id.clone());
                let theme = cx.theme();
                let id = id.clone();
                h_flex()
                    .id(("claude-code", ix))
                    .gap_2p5()
                    .px_2()
                    .py_1()
                    .rounded_md()
                    .cursor_pointer()
                    .text_size(row_text)
                    .when(active, |row| row.bg(theme.list_active))
                    .when(!active, |row| row.hover(|row| row.bg(theme.list_hover)))
                    .child(Icon::new(IconName::SquareTerminal).small().text_color(theme.muted_foreground))
                    .child(div().flex_1().min_w_0().truncate().child(name.clone()))
                    .on_click(
                        cx.listener(move |this, _, window, cx| this.go(Route::ClaudeCode(id.clone()), window, cx)),
                    )
                    .into_any_element()
            })
            .collect();
        let go_to = cx.listener(|this, _, window, cx| this.open_switcher(window, cx));
        let refresh = cx.listener(|this, _, _, cx| this.load_colonies(cx));
        let add = cx.listener(|this, _, window, cx| this.toggle_new_colony(window, cx));
        let new_colony = self.render_new_colony(cx);
        let adding = self.new_colony.is_some();
        let retry = cx.listener(|this, _, window, cx| this.load_queens(window, cx));
        let (colony_count, queen_count) = (self.colonies.len(), self.queens.len());
        let theme = cx.theme();
        // "COLONIES 1 ────" as the web heads its sections: small caps, a count, a hairline to the edge.
        let heading = |label: &'static str, count: Option<usize>| {
            h_flex()
                .flex_1()
                .gap_2()
                .px_2()
                .pt_5()
                .pb_1p5()
                .child(div().text_size(px(11.)).font_semibold().text_color(theme.muted_foreground).child(label))
                .when_some(count, |row, n| {
                    row.child(
                        div()
                            .px_1p5()
                            .rounded_full()
                            .bg(theme.muted)
                            .text_size(px(10.))
                            .text_color(theme.muted_foreground)
                            .child(n.to_string()),
                    )
                })
                .child(div().flex_1().h(px(1.)).bg(theme.border))
        };
        v_flex()
            .w(px(248.))
            .h_full()
            .flex_shrink_0()
            .bg(theme.sidebar)
            .border_r_1()
            .border_color(theme.sidebar_border)
            .child(
                v_flex()
                    .px_4()
                    .pt_4()
                    .pb_3()
                    .border_b_1()
                    .border_color(theme.sidebar_border)
                    .child(
                        h_flex()
                            .justify_between()
                            .child(
                                h_flex()
                                    .gap_1p5()
                                    .child(Icon::new(IconName::Hexagon).small().text_color(theme.primary))
                                    .child(
                                        h_flex()
                                            .text_size(px(15.))
                                            .font_semibold()
                                            .child("Open")
                                            .child(div().text_color(theme.primary).child("Hive")),
                                    ),
                            )
                            .child(
                                Button::new("go-to")
                                    .xsmall()
                                    .ghost()
                                    .icon(IconName::Search)
                                    .tooltip("Go to… (Ctrl+K)")
                                    .on_click(go_to),
                            ),
                    )
                    .child(
                        div()
                            .pl(px(22.))
                            .text_size(px(11.))
                            .text_color(theme.muted_foreground)
                            .child(api(cx).base().to_string()),
                    ),
            )
            .child(
                div().id("sidebar").flex_1().min_h_0().overflow_y_scroll().child(
                    v_flex()
                        .px_2()
                        .pt_2()
                        .pb_4()
                        .gap_px()
                        .children(nav)
                        .child(
                            h_flex().child(heading("COLONIES", Some(colony_count))).child(
                                h_flex()
                                    .pt_4()
                                    .child(
                                        Button::new("new-colony")
                                            .xsmall()
                                            .ghost()
                                            .icon(if adding { IconName::X } else { IconName::Plus })
                                            .tooltip("New colony")
                                            .on_click(add),
                                    )
                                    .child(
                                        Button::new("refresh-colonies")
                                            .xsmall()
                                            .ghost()
                                            .icon(IconName::RefreshCw)
                                            .tooltip("Reload")
                                            .on_click(refresh),
                                    ),
                            ),
                        )
                        .children(new_colony)
                        .when(colonies.is_empty(), |col| {
                            col.child(div().px_2().text_xs().text_color(theme.muted_foreground).child("None yet"))
                        })
                        .children(colonies)
                        .child(heading("QUEEN BEES", Some(queen_count)))
                        .children(queens)
                        .when(!claude_code.is_empty(), |col| {
                            col.child(heading("CLAUDE CODE", None)).children(claude_code)
                        })
                        .when_some(self.queens_error.clone(), |col, problem| {
                            col.child(
                                v_flex()
                                    .gap_2()
                                    .p_2()
                                    .child(ui::error_line(problem, theme))
                                    .child(Button::new("retry").small().outline().label("Try again").on_click(retry)),
                            )
                        }),
                ),
            )
    }
}

impl Render for Shell {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let main = match &self.route {
            Route::Queen(id) => self.chats.get(id).map(|chat| chat.clone().into_any_element()),
            Route::Page(page) => self.pages.get(page).map(|view| view.clone().into_any_element()),
            Route::Profile(id) => self.profiles.get(id).map(|view| view.clone().into_any_element()),
            Route::Colony(name) => self.colony_views.get(name).map(|view| view.clone().into_any_element()),
            Route::ClaudeCode(id) => self.claude_code.get(id).map(|view| view.clone().into_any_element()),
        };
        let switcher = self.render_switcher(cx);
        let degraded = self.live.read(cx).degraded().map(str::to_string);
        let theme = cx.theme();
        let banner = degraded.map(|reason| {
            h_flex()
                .gap_2()
                .px_4()
                .py_1p5()
                .bg(theme.warning)
                .text_color(theme.background)
                .text_sm()
                .child(Icon::new(IconName::WifiOff).small())
                .child(format!("The models can't be reached right now: {reason}"))
        });
        v_flex()
            .size_full()
            .relative()
            .key_context("Shell")
            .on_action(cx.listener(|this, _: &OpenSwitcher, window, cx| this.open_switcher(window, cx)))
            .on_action(cx.listener(|this, _: &CloseSwitcher, _, cx| {
                this.switcher = None;
                cx.notify();
            }))
            .bg(theme.background)
            .text_color(theme.foreground)
            .children(banner)
            .child(
                h_flex()
                    .flex_1()
                    .min_h_0()
                    .child(self.render_sidebar(cx))
                    .child(div().flex_1().h_full().min_w_0().children(main)),
            )
            .children(switcher)
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::{Colony, Page, Route, colonies_of, colony_slug, places_matching};
    use crate::api::Queen;
    use serde_json::json;

    #[test]
    fn lists_your_colonies_by_directory_name_from_either_path_style() {
        let discover = json!({
            "Framework": [{ "path": "/hive/framework/agents/x", "name": "x" }],
            "Your Agents": [
                { "path": "C:\\Users\\zed\\.hive\\colonies\\ivy_research", "name": "Ivy research" },
                { "path": "/home/zed/.hive/colonies/ava_outreach/", "name": "" },
            ],
        });
        let colonies = colonies_of(&discover);

        assert_eq!(
            colonies.iter().map(|c| (c.name.as_str(), c.label.as_str())).collect::<Vec<_>>(),
            vec![("ava_outreach", "ava outreach"), ("ivy_research", "Ivy research")]
        );
    }

    #[test]
    fn finds_places_by_any_words_of_their_names() {
        let queens = vec![Queen {
            id: "queen_ava".into(),
            name: "Ava".into(),
            title: "Head of Growth".into(),
            has_avatar: false,
            portrait: None,
        }];
        let colonies = vec![Colony { name: "ava_research".into(), label: "Ava research".into() }];
        let kinds =
            |q: &str| places_matching(q, &queens, &colonies, &[]).into_iter().map(|p| p.kind).collect::<Vec<_>>();

        assert_eq!(kinds("ava"), vec!["Chat", "Colony", "Profile"]);
        assert_eq!(kinds("growth ava"), vec!["Chat"]);
        assert_eq!(kinds("mod"), vec!["Page"]);
        // An empty query lists everything but the profiles.
        assert_eq!(kinds("").len(), 2 + Page::ALL.len());
    }

    #[test]
    fn turns_a_typed_name_into_a_colony_slug() {
        assert_eq!(colony_slug("  Ivy Research-2 "), "ivy_research_2");
        assert_eq!(colony_slug("Café ☕ list"), "caf__list");
    }

    #[test]
    fn parses_open_routes() {
        for route in [
            Route::Page(Page::OrgChart),
            Route::Queen("queen_ava".into()),
            Route::Profile("queen_ivy".into()),
            Route::Colony("zed_lab".into()),
        ] {
            assert!(Route::parse(&route.key()) == Some(route));
        }
        assert!(Route::parse("org-chart") == Some(Route::Page(Page::OrgChart)));
        assert!(Route::parse("colony:ivy_research") == Some(Route::Colony("ivy_research".into())));
        assert!(Route::parse("nowhere").is_none());
    }
}
