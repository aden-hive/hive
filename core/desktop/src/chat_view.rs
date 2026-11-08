//! One conversation, a queen's direct chat or a colony's: its history, the live stream, the
//! composer, and what the queen asks of the user along the way (answers, credentials, skill
//! installs, a colony to start).

use std::collections::{HashMap, HashSet};
use std::hash::{DefaultHasher, Hash, Hasher};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputEvent, InputState, Paste, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use crate::api::{Api, FilePart, HistoryCursor, Queen, SessionSummary, StreamEnd, api, base64, encode};
use crate::chat::{Chat, Item, Kind, Signal, ToolState, answer_text};
use crate::shell::{Page, Route};
use crate::{bg, ui};

actions!(chat, [Find]);

/// The web chat's page size (`EVENTS_PAGE_SIZE` in the frontend).
const HISTORY_PAGE: usize = 500;
/// Long reasoning is cut to this many characters until opened.
const THINKING_PREVIEW: usize = 400;
/// How often a colony's workers are re-read, as the web's workers panel does.
const WORKER_POLL: Duration = Duration::from_secs(2);
/// Busy with no event for this long, ask the server whether the queen is really still at it,
/// as the web chat's stall watchdog does.
const STALL_AFTER: Duration = Duration::from_secs(20);
const STALL_CHECK: Duration = Duration::from_secs(5);
/// The web composer's limits (`ChatPanel.tsx`): images go inline up to 10 MB; other files are
/// uploaded, up to 100 MB.
const IMAGE_LIMIT: u64 = 10 * 1024 * 1024;
const FILE_LIMIT: u64 = 100 * 1024 * 1024;

#[derive(Clone)]
pub enum Target {
    Queen(Queen),
    /// The colony's directory name.
    Colony(String),
}

/// Which of the queen's direct chats to show. A colony has one chat, so it always opens `Latest`.
pub enum Opening {
    /// Her running chat, else her newest.
    Latest,
    Session(String),
    New,
}

/// What the view asks of whoever holds it.
pub enum ChatEvent {
    Go(Route),
    /// The conversation now runs as this session.
    Session(String),
    /// The colony's side panel button was pressed.
    TogglePanel,
    /// A colony was renamed or deleted: drop its view, reload the list, then go to `go`.
    ColonyChanged {
        forget: String,
        go: Route,
    },
}

/// What a stream thread hands the view.
enum Feed {
    Connected,
    Event(Value),
    Problem(String),
    /// The session was stopped, or its colony deleted or renamed, elsewhere; the stream gave up.
    Ended,
}

/// How a stopped session is brought back so its stream can be read again.
enum Resume {
    Queen(String),
    Colony(String),
}

/// A file picked for the next message, already in the shape `/chat` takes.
struct Attachment {
    name: String,
    part: Value,
}

/// Answers being given to the queen's pending questions.
struct QuestionForm {
    /// Which questions this form is for, to notice a new set.
    ids: Vec<String>,
    picked: Vec<Option<String>>,
    /// The "something else" answer per question.
    others: Vec<Entity<InputState>>,
}

/// The queen asked for a credential (`client_credential_form_requested`).
struct CredentialForm {
    data: Value,
    /// (key name, label, input)
    fields: Vec<(String, String, Entity<InputState>)>,
    error: Option<String>,
    saving: bool,
}

/// The queen suggested starting a colony.
struct Suggestion {
    data: Value,
    slug: Entity<InputState>,
    error: Option<String>,
    working: bool,
}

enum Picture {
    Loading,
    Ready(Arc<Image>),
    Failed,
}

/// The find bar: what's searched for, and which match is shown.
struct FindBar {
    query: Entity<InputState>,
    /// Index into the current matches.
    current: usize,
}

pub struct ChatView {
    target: Target,
    /// The queen in charge; for a colony, learned when its session opens.
    queen: Option<Queen>,
    session_id: Option<String>,
    title: Option<String>,
    /// Every event applied so far, oldest first; older history is put in front and replayed.
    events: Vec<Value>,
    chat: Chat,
    older: Option<HistoryCursor>,
    loading_older: bool,
    /// Shown under the header: opening, reconnecting, or why something failed.
    status: Option<String>,
    /// Feeds and results tagged with an older generation belong to a chat this view has left.
    generation: u64,
    stop: Arc<AtomicBool>,
    composer: Entity<TextareaState>,
    /// The messages, laid out only where they show: a long chat would otherwise lay out every
    /// bubble again on each streamed word. It follows the newest message until you scroll up.
    list: ListState,
    /// A fingerprint per item as last laid out, to remeasure only the ones that changed.
    laid_out: Vec<u64>,
    /// Whether the list's first row is the "Load earlier messages" button.
    list_has_older: bool,
    /// The queen's chats, listed beside this one when open.
    sessions: Option<Result<Vec<SessionSummary>, String>>,
    sessions_open: bool,
    /// The session's plan, shown beside the chat when open.
    plan: Option<Result<Value, String>>,
    plan_open: bool,
    /// Tool calls, thinking and workers the user opened for detail.
    expanded: HashSet<String>,
    /// A message to send once the chat being opened is ready.
    outbox: Option<String>,
    attachments: Vec<Attachment>,
    attaching: bool,
    /// The stream gave up because the session stopped; the next message starts it again.
    ended: bool,
    questions: Option<QuestionForm>,
    credential: Option<CredentialForm>,
    /// Pending skill install requests, oldest first; the first is shown.
    installs: Vec<Value>,
    install_body_open: bool,
    deciding: bool,
    suggestion: Option<Suggestion>,
    renaming: Option<Entity<InputState>>,
    /// Images in user messages, by session-relative path.
    pictures: HashMap<String, Picture>,
    /// A colony's workers by id, from the workers list.
    workers: HashMap<String, Value>,
    panel_open: bool,
    /// When the stream last delivered an event, for the stall watchdog.
    last_event: Instant,
    find: Option<FindBar>,
    tasks: Vec<Task<()>>,
    _subscriptions: Vec<Subscription>,
}

impl EventEmitter<ChatEvent> for ChatView {}

impl Drop for ChatView {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}

/// The MIME type of an image the queen can see, by extension; `None` for anything else.
fn image_mime(ext: &str) -> Option<&'static str> {
    match ext {
        "png" => Some("image/png"),
        "jpg" | "jpeg" => Some("image/jpeg"),
        "gif" => Some("image/gif"),
        "webp" => Some("image/webp"),
        _ => None,
    }
}

/// Read a picked file into an attachment: images inline, anything else uploaded to the session.
fn prepare(api: &Api, session_id: &str, path: &Path) -> anyhow::Result<Attachment> {
    let name = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "file".into());
    let ext = path.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
    let size = std::fs::metadata(path)?.len();
    let url = match image_mime(&ext) {
        Some(mime) => {
            anyhow::ensure!(size <= IMAGE_LIMIT, "{name} is over 10 MB");
            format!("data:{mime};base64,{}", base64(&std::fs::read(path)?))
        }
        None => {
            anyhow::ensure!(size <= FILE_LIMIT, "{name} is over 100 MB");
            let content_type = match ext.as_str() {
                "pdf" => "application/pdf",
                "csv" => "text/csv",
                "txt" | "md" => "text/plain",
                "json" => "application/json",
                _ => "application/octet-stream",
            };
            api.upload_attachment(
                session_id,
                FilePart {
                    field: "file".into(),
                    filename: name.clone(),
                    content_type: content_type.into(),
                    bytes: std::fs::read(path)?,
                },
            )?
        }
    };
    Ok(Attachment { name, part: json!({ "type": "image_url", "image_url": { "url": url } }) })
}

/// The runtime's text for a failed model call, `[Error: LLM call failed: …]`, as `ModelErrorCard.tsx` spots it.
fn model_error(text: &str) -> Option<&str> {
    let inner = text.trim().strip_prefix("[Error: LLM call failed: ")?.strip_suffix(']')?;
    Some(inner.strip_suffix(". Please try again.").unwrap_or(inner))
}

/// The (question, answer) pairs of a message made only of `"prompt"="answer"` lines, two or more,
/// which is how answers to several questions are sent.
fn qa_pairs(text: &str) -> Option<Vec<(String, String)>> {
    let pairs: Option<Vec<(String, String)>> = text
        .lines()
        .map(|line| {
            let (q, a) = line.strip_prefix('"')?.strip_suffix('"')?.split_once("\"=\"")?;
            Some((q.to_string(), a.to_string()))
        })
        .collect();
    pairs.filter(|p| p.len() >= 2)
}

fn is_key_problem(error: &str) -> bool {
    let e = error.to_lowercase();
    ["authenticationerror", "api_key", "api key", "api-key", "401", "unauthorized", "unauthorised", "permission denied"]
        .iter()
        .any(|k| e.contains(k))
}

impl ChatView {
    pub fn new(target: Target, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let placeholder = match &target {
            Target::Queen(q) => format!("Message {}…", q.name),
            Target::Colony(name) => format!("Message the {name} colony…"),
        };
        let composer =
            cx.new(|cx| TextareaState::new(window, cx).auto_grow(1, 8).submit_on_enter(true).placeholder(placeholder));
        let subscription = cx.subscribe_in(&composer, window, |this, _, event: &InputEvent, window, cx| {
            if let InputEvent::PressEnter { shift: false, .. } = event {
                this.send(window, cx);
            }
        });
        let queen = match &target {
            Target::Queen(q) => Some(q.clone()),
            Target::Colony(_) => None,
        };
        let mut view = Self {
            target,
            queen,
            session_id: None,
            title: None,
            events: Vec::new(),
            chat: Chat::default(),
            older: None,
            loading_older: false,
            status: None,
            generation: 0,
            stop: Arc::new(AtomicBool::new(false)),
            composer,
            list: ListState::new(0, ListAlignment::Top, px(1024.)),
            laid_out: Vec::new(),
            list_has_older: false,
            sessions: None,
            sessions_open: false,
            plan: None,
            plan_open: false,
            expanded: HashSet::new(),
            outbox: None,
            attachments: Vec::new(),
            attaching: false,
            ended: false,
            questions: None,
            credential: None,
            installs: Vec::new(),
            install_body_open: false,
            deciding: false,
            suggestion: None,
            renaming: None,
            pictures: HashMap::new(),
            workers: HashMap::new(),
            panel_open: false,
            last_event: Instant::now(),
            find: None,
            tasks: Vec::new(),
            _subscriptions: vec![subscription],
        };
        view.list.set_follow_mode(FollowMode::Tail);
        view.open(Opening::Latest, window, cx);
        view
    }

    /// Put the cursor in the composer once it's on screen; a view opened this frame has none to focus yet.
    pub fn focus(&self, window: &mut Window, cx: &mut Context<Self>) {
        cx.on_next_frame(window, |this, window, cx| this.composer.update(cx, |state, cx| state.focus(window, cx)));
    }

    pub fn set_panel_open(&mut self, open: bool, cx: &mut Context<Self>) {
        self.panel_open = open;
        cx.notify();
    }

    fn is_colony(&self) -> bool {
        matches!(self.target, Target::Colony(_))
    }

    /// Send `text` as soon as there's a chat to send it in; in a new chat if `fresh`.
    pub fn send_soon(&mut self, text: String, fresh: bool, window: &mut Window, cx: &mut Context<Self>) {
        if fresh && !self.is_colony() {
            self.outbox = Some(text);
            self.open(Opening::New, window, cx);
        } else if self.session_id.is_some() {
            self.send_text(text, Vec::new(), window, cx);
        } else {
            self.outbox = Some(text);
        }
    }

    /// Leave whatever chat is showing and load another.
    pub fn open(&mut self, how: Opening, window: &mut Window, cx: &mut Context<Self>) {
        self.stop.store(true, Ordering::Relaxed);
        self.stop = Arc::new(AtomicBool::new(false));
        self.generation += 1;
        self.session_id = None;
        self.title = None;
        self.events.clear();
        self.chat = Chat::default();
        self.older = None;
        self.attachments.clear();
        self.attaching = false;
        self.ended = false;
        self.list.scroll_to_end();
        self.expanded.clear();
        self.tasks.clear();
        self.questions = None;
        self.credential = None;
        self.installs.clear();
        self.suggestion = None;
        self.renaming = None;
        self.workers.clear();
        self.status = Some(match how {
            Opening::New => "Starting a new chat…".into(),
            _ => "Opening the chat…".into(),
        });
        let generation = self.generation;
        let api = api(cx);
        let target = self.target.clone();
        let task = bg::spawn_in(
            window,
            cx,
            move || {
                let (session_id, queen) = match &target {
                    Target::Queen(queen) => {
                        let id = match how {
                            Opening::Latest => api.open_session(&queen.id)?,
                            Opening::Session(id) => api.select_session(&queen.id, &id)?,
                            Opening::New => api.new_session(&queen.id)?,
                        };
                        (id, None)
                    }
                    Target::Colony(name) => {
                        let session = api.open_colony(name)?;
                        let queen_id = session["queen_id"].as_str().unwrap_or_default().to_string();
                        // The profile carries her title and whether she has a picture.
                        let queen =
                            api.queens().ok().and_then(|qs| qs.into_iter().find(|q| q.id == queen_id)).or_else(|| {
                                (!queen_id.is_empty()).then(|| Queen {
                                    id: queen_id.clone(),
                                    name: session["queen_name"].as_str().unwrap_or(&queen_id).to_string(),
                                    title: String::new(),
                                    has_avatar: false,
                                    portrait: None,
                                })
                            });
                        (session["session_id"].as_str().unwrap_or_default().to_string(), queen)
                    }
                };
                let page = api.history(&session_id, HISTORY_PAGE, None)?;
                let title = api
                    .sessions()
                    .ok()
                    .and_then(|all| all.into_iter().find(|s| s.session_id == session_id))
                    .and_then(|s| s.title)
                    .filter(|t| !t.is_empty());
                anyhow::Ok((session_id, queen, title, page))
            },
            move |this: &mut Self, opened, window, cx| {
                if this.generation != generation {
                    return;
                }
                match opened {
                    Ok((session_id, queen, title, page)) => {
                        if queen.is_some() {
                            this.queen = queen;
                        }
                        this.title = title;
                        this.session_id = Some(session_id.clone());
                        this.older = page.older;
                        this.status = Some("Connecting…".into());
                        let signals = this.chat.apply_all(&page.events);
                        this.events = page.events;
                        this.start_stream(window, cx);
                        // A form or suggestion in history was answered or dropped long ago; only live ones are shown.
                        this.handle(
                            signals
                                .into_iter()
                                .filter(|s| !matches!(s, Signal::CredentialForm(_) | Signal::ColonySuggestion(_))),
                            window,
                            cx,
                        );
                        this.load_installs(cx);
                        if this.sessions_open {
                            this.load_sessions(cx);
                        }
                        if this.plan_open {
                            this.load_plan(cx);
                        }
                        if this.is_colony() {
                            this.poll_workers(cx);
                        }
                        this.watch_stall(cx);
                        cx.emit(ChatEvent::Session(session_id));
                        if let Some(text) = this.outbox.take() {
                            this.send_text(text, Vec::new(), window, cx);
                        }
                    }
                    Err(e) => this.status = Some(format!("Couldn't open the chat: {e}")),
                }
            },
        );
        self.tasks.push(task);
        cx.notify();
    }

    /// Read the session's live events on a thread and apply them here as they come.
    fn start_stream(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let (tx, rx) = smol::channel::unbounded();
        let api = api(cx);
        let resume = match &self.target {
            Target::Queen(q) => Resume::Queen(q.id.clone()),
            Target::Colony(name) => Resume::Colony(name.clone()),
        };
        let stop = self.stop.clone();
        std::thread::spawn(move || stream_loop(&api, &session_id, &resume, &stop, &tx));
        let generation = self.generation;
        self.tasks.push(cx.spawn_in(window, async move |this, cx| {
            while let Ok(feed) = rx.recv().await {
                if this.update_in(cx, |view, window, cx| view.on_feed(generation, feed, window, cx)).is_err() {
                    break;
                }
            }
        }));
    }

    fn on_feed(&mut self, generation: u64, feed: Feed, window: &mut Window, cx: &mut Context<Self>) {
        if self.generation != generation {
            return;
        }
        let signal = match feed {
            Feed::Connected => {
                self.status = None;
                None
            }
            Feed::Problem(problem) => {
                self.status = Some(problem);
                None
            }
            Feed::Ended => {
                self.ended = true;
                self.chat.busy = false;
                self.status = Some(if self.is_colony() {
                    "This colony's chat stopped; it may have been renamed or deleted. Reopen it from the sidebar."
                        .into()
                } else {
                    "This chat stopped running. Sending a message starts it again.".into()
                });
                None
            }
            Feed::Event(event) => {
                self.last_event = Instant::now();
                let signal = self.chat.apply(&event);
                self.events.push(event);
                signal
            }
        };
        self.handle(signal, window, cx);
        cx.notify();
    }

    fn handle(&mut self, signals: impl IntoIterator<Item = Signal>, window: &mut Window, cx: &mut Context<Self>) {
        for signal in signals {
            match signal {
                Signal::Forked(new_id) => {
                    self.stop.store(true, Ordering::Relaxed);
                    self.stop = Arc::new(AtomicBool::new(false));
                    self.generation += 1;
                    self.session_id = Some(new_id.clone());
                    self.older = None;
                    self.ended = false;
                    self.start_stream(window, cx);
                    if self.is_colony() {
                        self.poll_workers(cx);
                    }
                    self.watch_stall(cx);
                    cx.emit(ChatEvent::Session(new_id));
                }
                Signal::Title(title) => self.title = Some(title).filter(|t| !t.is_empty()),
                Signal::SkillInstalls => self.load_installs(cx),
                Signal::CredentialForm(data) => self.show_credential_form(data, window, cx),
                Signal::ColonySuggestion(data) => {
                    let slug = data["colony_id"].as_str().unwrap_or_default().to_string();
                    let input = cx.new(|cx| InputState::new(window, cx).placeholder("colony_name").default_value(slug));
                    self.suggestion = Some(Suggestion { data, slug: input, error: None, working: false });
                }
                Signal::Tasks if self.plan_open => self.load_plan(cx),
                // The colony panel follows these through its own stream.
                Signal::Tasks | Signal::Triggers | Signal::Workers => {}
            }
        }
    }

    /// Clear a "Thinking…" the stream never ended: when busy and quiet for a while, read the
    /// session's snapshot, and stop showing busy unless the queen is thinking or in a tool.
    fn watch_stall(&mut self, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let generation = self.generation;
        let api = api(cx);
        self.tasks.push(cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor().timer(STALL_CHECK).await;
                let stalled = this.update(cx, |view, _| {
                    (view.generation == generation).then(|| view.chat.busy && view.last_event.elapsed() >= STALL_AFTER)
                });
                match stalled {
                    Ok(Some(true)) => {}
                    Ok(Some(false)) => continue,
                    _ => break,
                }
                let (api2, sid) = (api.clone(), session_id.clone());
                let snapshot = cx.background_spawn(async move { api2.get(&format!("/sessions/{sid}/snapshot")) }).await;
                this.update(cx, |view, cx| {
                    // Wait out another quiet spell before asking again.
                    view.last_event = Instant::now();
                    if view.generation == generation
                        && let Ok(snapshot) = snapshot
                        && !matches!(snapshot["queen_busy_reason"].as_str(), Some("llm" | "tool"))
                    {
                        view.chat.busy = false;
                        cx.notify();
                    }
                })
                .ok();
            }
        }));
    }

    /// Keep a colony's workers fresh while its chat is open.
    fn poll_workers(&mut self, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let generation = self.generation;
        let api = api(cx);
        self.tasks.push(cx.spawn(async move |this, cx| {
            loop {
                let (api2, sid) = (api.clone(), session_id.clone());
                let listed = cx.background_spawn(async move { api2.get(&format!("/sessions/{sid}/workers")) }).await;
                let keep = this
                    .update(cx, |view, cx| {
                        if view.generation != generation {
                            return false;
                        }
                        if let Ok(body) = listed {
                            let workers: HashMap<String, Value> = body["workers"]
                                .as_array()
                                .into_iter()
                                .flatten()
                                .map(|w| (w["worker_id"].as_str().unwrap_or_default().to_string(), w.clone()))
                                .collect();
                            if workers != view.workers {
                                view.workers = workers;
                                // Worker cards change height with what their workers report.
                                view.list.remeasure();
                                cx.notify();
                            }
                        }
                        true
                    })
                    .unwrap_or(false);
                if !keep {
                    break;
                }
                cx.background_executor().timer(WORKER_POLL).await;
            }
        }));
    }

    fn load_older(&mut self, cx: &mut Context<Self>) {
        let (Some(cursor), Some(session_id)) = (self.older, self.session_id.clone()) else { return };
        if self.loading_older {
            return;
        }
        self.loading_older = true;
        let generation = self.generation;
        let api = api(cx);
        let task = bg::spawn(
            cx,
            move || api.history(&session_id, HISTORY_PAGE, Some(cursor)),
            move |this: &mut Self, page, _| {
                this.loading_older = false;
                if this.generation != generation {
                    return;
                }
                match page {
                    Ok(page) => {
                        let mut events = page.events;
                        events.append(&mut this.events);
                        // Replaying from the start keeps every bubble where the web chat puts it.
                        let pending = std::mem::take(&mut this.chat.pending);
                        this.chat = Chat::default();
                        this.chat.apply_all(&events);
                        this.chat.pending = pending;
                        this.events = events;
                        this.older = page.older;
                    }
                    Err(e) => this.chat.local_notice(format!("Couldn't load earlier messages: {e}")),
                }
            },
        );
        self.tasks.push(task);
    }

    fn send(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let text = self.composer.read(cx).value().trim().to_string();
        if text.is_empty() && self.attachments.is_empty() {
            return;
        }
        self.composer.update(cx, |state, cx| state.set_value("", window, cx));
        let attachments = std::mem::take(&mut self.attachments);
        self.send_text(text, attachments, window, cx);
    }

    /// Post a message, putting the words back in the composer if it couldn't be delivered.
    fn send_text(&mut self, text: String, attachments: Vec<Attachment>, window: &mut Window, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        // Starting a stopped colony chat again would recreate a colony deleted elsewhere.
        let restart = match (&self.target, self.ended) {
            (_, false) => None,
            (Target::Queen(q), true) => Some(q.id.clone()),
            (Target::Colony(_), true) => {
                self.composer.update(cx, |state, cx| state.set_value(text, window, cx));
                self.attachments = attachments;
                cx.notify();
                return;
            }
        };
        self.chat.busy = true;
        self.list.scroll_to_end();
        let generation = self.generation;
        let api = api(cx);
        let message = text.clone();
        let display = (!attachments.is_empty()).then(|| {
            if text.is_empty() {
                attachments.iter().map(|a| format!("[{}]", a.name)).collect::<Vec<_>>().join(" ")
            } else {
                text.clone()
            }
        });
        let parts: Vec<Value> = attachments.iter().map(|a| a.part.clone()).collect();
        bg::spawn_in(
            window,
            cx,
            move || {
                if let Some(queen_id) = &restart {
                    api.resume(&session_id, queen_id)?;
                }
                if parts.is_empty() {
                    api.send(&session_id, &message)?;
                } else {
                    api.send_with(&session_id, &message, parts, display)?;
                }
                anyhow::Ok(restart.is_some())
            },
            move |this: &mut Self, sent, window, cx| {
                let e = match sent {
                    Ok(restarted) => {
                        if restarted && this.generation == generation && this.ended {
                            this.ended = false;
                            this.status = Some("Connecting…".into());
                            this.start_stream(window, cx);
                        }
                        return;
                    }
                    Err(e) => e,
                };
                // Give the words and files back unless something new has been typed since.
                if this.composer.read(cx).value().is_empty() {
                    this.composer.update(cx, |state, cx| state.set_value(text, window, cx));
                    if this.attachments.is_empty() {
                        this.attachments = attachments;
                    }
                }
                if this.generation == generation {
                    this.chat.busy = false;
                    this.chat.local_notice(format!("Couldn't send: {e}"));
                }
            },
        )
        .detach();
        cx.notify();
    }

    fn attach(&mut self, cx: &mut Context<Self>) {
        let picked = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: true,
            prompt: Some("Attach".into()),
        });
        cx.spawn(async move |this, cx| {
            let paths = picked.await.ok().and_then(Result::ok).flatten().unwrap_or_default();
            this.update(cx, |view, cx| view.attach_paths(paths, cx)).ok();
        })
        .detach();
    }

    /// Ready these files for the next message, off the UI thread: images inline, others uploaded.
    fn attach_paths(&mut self, paths: Vec<PathBuf>, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        if paths.is_empty() {
            return;
        }
        let api = api(cx);
        self.attaching = true;
        let generation = self.generation;
        cx.spawn(async move |this, cx| {
            let prepared = cx
                .background_spawn(
                    async move { paths.iter().map(|p| prepare(&api, &session_id, p)).collect::<Vec<_>>() },
                )
                .await;
            this.update(cx, |view, cx| {
                // Uploaded into the chat that was open then; another chat can't use them.
                if view.generation != generation {
                    return;
                }
                view.attaching = false;
                for attachment in prepared {
                    match attachment {
                        Ok(a) => view.attachments.push(a),
                        Err(e) => view.chat.local_notice(format!("Couldn't attach: {e}")),
                    }
                }
                cx.notify();
            })
            .ok();
        })
        .detach();
        cx.notify();
    }

    /// Take an image or files from the clipboard as attachments. Returns false for anything else,
    /// so the composer pastes text as usual.
    fn paste_attachments(&mut self, cx: &mut Context<Self>) -> bool {
        let Some(item) = cx.read_from_clipboard() else { return false };
        let mut taken = false;
        for entry in item.entries() {
            match entry {
                ClipboardEntry::Image(image) => {
                    taken = true;
                    let mime = match image.format {
                        ImageFormat::Png => "image/png",
                        ImageFormat::Jpeg => "image/jpeg",
                        ImageFormat::Gif => "image/gif",
                        ImageFormat::Webp => "image/webp",
                        _ => {
                            self.chat.local_notice("That image's format can't be sent; paste a PNG or JPEG.".into());
                            continue;
                        }
                    };
                    if image.bytes.len() as u64 > IMAGE_LIMIT {
                        self.chat.local_notice("The pasted image is over 10 MB.".into());
                        continue;
                    }
                    let url = format!("data:{mime};base64,{}", base64(&image.bytes));
                    let name = format!("Pasted image {}", self.attachments.len() + 1);
                    self.attachments
                        .push(Attachment { name, part: json!({ "type": "image_url", "image_url": { "url": url } }) });
                }
                ClipboardEntry::ExternalPaths(paths) => {
                    taken = true;
                    self.attach_paths(paths.paths().to_vec(), cx);
                }
                ClipboardEntry::String(_) => {}
            }
        }
        if taken {
            cx.notify();
        }
        taken
    }

    fn stop_turn(&mut self, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let generation = self.generation;
        let colony = self.is_colony();
        let api = api(cx);
        bg::spawn(
            cx,
            move || {
                // A colony's workers stop with the queen, as the web's Stop does.
                if colony {
                    api.post(&format!("/sessions/{session_id}/workers/stop-all"), json!({}))?;
                }
                api.cancel(&session_id)
            },
            move |this: &mut Self, cancelled, _| {
                if this.generation != generation {
                    return;
                }
                match cancelled {
                    Ok(()) => this.chat.busy = false,
                    Err(e) => this.chat.local_notice(format!("Couldn't stop: {e}")),
                }
            },
        )
        .detach();
    }

    fn toggle_sessions(&mut self, cx: &mut Context<Self>) {
        self.sessions_open = !self.sessions_open;
        if self.sessions_open {
            self.plan_open = false;
            self.load_sessions(cx);
        }
        cx.notify();
    }

    fn toggle_plan(&mut self, cx: &mut Context<Self>) {
        self.plan_open = !self.plan_open;
        if self.plan_open {
            self.sessions_open = false;
            self.load_plan(cx);
        }
        cx.notify();
    }

    fn load_plan(&mut self, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || crate::plan::load(&api, &session_id),
            |this: &mut Self, got, _| this.plan = Some(got.map_err(|e| e.to_string())),
        ));
    }

    fn load_sessions(&mut self, cx: &mut Context<Self>) {
        let Target::Queen(queen) = &self.target else { return };
        let api = api(cx);
        let queen_id = queen.id.clone();
        let task = bg::spawn(
            cx,
            move || {
                let mut mine: Vec<SessionSummary> =
                    api.sessions()?.into_iter().filter(|s| s.queen_id.as_deref() == Some(queen_id.as_str())).collect();
                // Live first, then by last activity, as the web's switcher orders them.
                mine.sort_by(|a, b| {
                    b.live.cmp(&a.live).then(
                        b.last_active_at
                            .or(b.created_at)
                            .unwrap_or(0.0)
                            .total_cmp(&a.last_active_at.or(a.created_at).unwrap_or(0.0)),
                    )
                });
                anyhow::Ok(mine)
            },
            |this: &mut Self, sessions, _| this.sessions = Some(sessions.map_err(|e| e.to_string())),
        );
        self.tasks.push(task);
    }

    fn start_rename(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let current = self.title.clone().unwrap_or_default();
        let input = cx.new(|cx| InputState::new(window, cx).placeholder("Name this chat").default_value(current));
        let save = cx.subscribe_in(&input, window, |this, _, event: &InputEvent, _, cx| {
            if let InputEvent::PressEnter { .. } = event {
                this.save_title(cx);
            }
        });
        self._subscriptions.push(save);
        input.update(cx, |s, cx| s.focus(window, cx));
        self.renaming = Some(input);
        cx.notify();
    }

    fn save_title(&mut self, cx: &mut Context<Self>) {
        let (Some(input), Some(session_id)) = (self.renaming.take(), self.session_id.clone()) else { return };
        // The server keeps 60 characters at most, as the web's field allows.
        let title: String = input.read(cx).value().trim().chars().take(60).collect();
        let api = api(cx);
        let generation = self.generation;
        bg::spawn(
            cx,
            move || api.patch(&format!("/sessions/{session_id}/title"), json!({ "title": title })),
            move |this: &mut Self, saved, cx| match saved {
                // Renamed a chat that's no longer the one showing.
                _ if this.generation != generation => {}
                Ok(body) => {
                    this.title = body["title"].as_str().map(str::to_string).filter(|t| !t.is_empty());
                    if this.sessions_open {
                        this.load_sessions(cx);
                    }
                }
                Err(e) => this.chat.local_notice(format!("Couldn't rename the chat: {e}")),
            },
        )
        .detach();
        cx.notify();
    }

    fn open_find(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if let Some(find) = &self.find {
            find.query.update(cx, |s, cx| s.focus(window, cx));
            return;
        }
        let query = cx.new(|cx| InputState::new(window, cx).placeholder("Find in this chat"));
        cx.observe(&query, |this, _, cx| {
            if let Some(find) = this.find.as_mut() {
                find.current = 0;
            }
            this.reveal_match(cx);
        })
        .detach();
        let next = cx.subscribe_in(&query, window, |this, _, event: &InputEvent, _, cx| {
            if let InputEvent::PressEnter { shift, .. } = event {
                this.step_find(if *shift { -1 } else { 1 }, cx);
            }
        });
        self._subscriptions.push(next);
        query.update(cx, |s, cx| s.focus(window, cx));
        self.find = Some(FindBar { query, current: 0 });
        cx.notify();
    }

    fn close_find(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.find = None;
        self.composer.update(cx, |s, cx| s.focus(window, cx));
        cx.notify();
    }

    /// Items whose text holds the query, ignoring case.
    fn matches(&self, cx: &App) -> Vec<usize> {
        let Some(find) = &self.find else { return Vec::new() };
        let query = find.query.read(cx).value().trim().to_lowercase();
        if query.is_empty() {
            return Vec::new();
        }
        self.chat
            .items
            .iter()
            .enumerate()
            .filter(|(_, item)| item.text.to_lowercase().contains(&query))
            .map(|(ix, _)| ix)
            .collect()
    }

    fn step_find(&mut self, by: isize, cx: &mut Context<Self>) {
        let count = self.matches(cx).len();
        if let Some(find) = self.find.as_mut()
            && count > 0
        {
            find.current = (find.current as isize + by).rem_euclid(count as isize) as usize;
        }
        self.reveal_match(cx);
    }

    /// Scroll the current match into view; the newest match comes first, as you read back from the end.
    fn reveal_match(&mut self, cx: &mut Context<Self>) {
        let matches = self.matches(cx);
        if let Some(find) = &self.find
            && let Some(&ix) = matches.iter().rev().nth(find.current)
        {
            // Following the newest message would pull the view straight back down; it resumes
            // once you scroll to the bottom again.
            self.list.pause_following_tail();
            self.list.scroll_to_reveal_item(ix + self.list_has_older as usize);
        }
        cx.notify();
    }

    /// The item the find bar points at, if any.
    fn found(&self, cx: &App) -> Option<usize> {
        let find = self.find.as_ref()?;
        self.matches(cx).iter().rev().nth(find.current).copied()
    }

    fn render_find(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        let find = self.find.as_ref()?;
        let count = self.matches(cx).len();
        let theme = cx.theme().clone();
        let place = if count == 0 { "No matches".to_string() } else { format!("{} of {count}", find.current + 1) };
        Some(
            h_flex()
                .gap_2()
                .px_5()
                .py_1p5()
                .border_b_1()
                .border_color(theme.border)
                .child(div().w(px(320.)).child(Input::new(&find.query).small()))
                .child(div().text_xs().text_color(theme.muted_foreground).child(place))
                .child(
                    Button::new("find-older")
                        .xsmall()
                        .ghost()
                        .icon(IconName::ChevronUp)
                        .tooltip("Older match")
                        .on_click(cx.listener(|this, _, _, cx| this.step_find(1, cx))),
                )
                .child(
                    Button::new("find-newer")
                        .xsmall()
                        .ghost()
                        .icon(IconName::ChevronDown)
                        .tooltip("Newer match")
                        .on_click(cx.listener(|this, _, _, cx| this.step_find(-1, cx))),
                )
                .child(
                    Button::new("find-close")
                        .xsmall()
                        .ghost()
                        .icon(IconName::X)
                        .tooltip("Close")
                        .on_click(cx.listener(|this, _, window, cx| this.close_find(window, cx))),
                )
                .into_any_element(),
        )
    }

    fn toggle_expanded(&mut self, id: &str, cx: &mut Context<Self>) {
        if !self.expanded.remove(id) {
            self.expanded.insert(id.to_string());
        }
        cx.notify();
    }

    // ----- What the queen asks of the user -----

    /// Rebuild the answer form when the pending questions change.
    fn sync_questions(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let ids: Vec<String> = self.chat.pending.iter().map(|q| q.id.clone()).collect();
        if ids.is_empty() {
            self.questions = None;
            return;
        }
        if self.questions.as_ref().is_some_and(|f| f.ids == ids) {
            return;
        }
        let others = self
            .chat
            .pending
            .iter()
            .map(|q| {
                let hint = if q.options.is_empty() { "Your answer" } else { "Something else…" };
                let input = cx.new(|cx| InputState::new(window, cx).placeholder(hint));
                cx.observe(&input, |_, _, cx| cx.notify()).detach();
                input
            })
            .collect();
        self.questions = Some(QuestionForm { picked: vec![None; ids.len()], ids, others });
    }

    /// The answer to each question, if every one has one.
    fn answers(&self, cx: &App) -> Option<Vec<String>> {
        let form = self.questions.as_ref()?;
        form.picked
            .iter()
            .zip(&form.others)
            .map(|(picked, other)| {
                let typed = other.read(cx).value().trim().to_string();
                if !typed.is_empty() { Some(typed) } else { picked.clone() }
            })
            .collect()
    }

    fn submit_answers(&mut self, answers: Vec<String>, window: &mut Window, cx: &mut Context<Self>) {
        let text = answer_text(&self.chat.pending, &answers);
        self.chat.pending.clear();
        self.questions = None;
        self.send_text(text, Vec::new(), window, cx);
    }

    fn pick_answer(&mut self, question: usize, option: String, window: &mut Window, cx: &mut Context<Self>) {
        // One question answered by one click; several wait for "Send answers".
        if self.chat.pending.len() == 1 {
            self.submit_answers(vec![option], window, cx);
            return;
        }
        if let Some(form) = self.questions.as_mut() {
            form.picked[question] = Some(option);
            form.others[question].update(cx, |s, cx| s.set_value("", window, cx));
        }
        cx.notify();
    }

    fn show_credential_form(&mut self, data: Value, window: &mut Window, cx: &mut Context<Self>) {
        if data["credential_id"].as_str().is_none() || data["correlation_id"].as_str().is_none() {
            return;
        }
        let fields = data["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|f| {
                let name = f["name"].as_str().unwrap_or_default().to_string();
                let label = f["label"].as_str().filter(|l| !l.is_empty()).unwrap_or(&name).to_string();
                let secret = f["secret"].as_bool().unwrap_or(false);
                let placeholder = f["placeholder"].as_str().unwrap_or_default().to_string();
                let input = cx.new(|cx| InputState::new(window, cx).placeholder(placeholder).masked(secret));
                (name, label, input)
            })
            .collect::<Vec<_>>();
        if fields.is_empty() {
            return;
        }
        self.credential = Some(CredentialForm { data, fields, error: None, saving: false });
    }

    fn answer_credential(&mut self, save: bool, cx: &mut Context<Self>) {
        let (Some(form), Some(session_id)) = (self.credential.as_mut(), self.session_id.clone()) else { return };
        let keys: serde_json::Map<String, Value> = form
            .fields
            .iter()
            .filter_map(|(name, _, input)| {
                let value = input.read(cx).value().trim().to_string();
                (!value.is_empty()).then(|| (name.clone(), json!(value)))
            })
            .collect();
        let body = json!({
            "correlation_id": form.data["correlation_id"],
            "status": if save { "saved" } else { "cancelled" },
            "credential_id": form.data["credential_id"],
            "account": form.data["account"],
            "keys": if save { Value::Object(keys) } else { json!({}) },
        });
        form.saving = true;
        let api = api(cx);
        bg::spawn(
            cx,
            move || api.post(&format!("/sessions/{session_id}/credential-form"), body),
            |this: &mut Self, answered, _| match answered {
                Ok(_) => this.credential = None,
                Err(e) => {
                    if let Some(form) = this.credential.as_mut() {
                        form.saving = false;
                        form.error = Some(e.to_string());
                    }
                }
            },
        )
        .detach();
        cx.notify();
    }

    fn load_installs(&mut self, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let generation = self.generation;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get(&format!("/sessions/{session_id}/skill-installs")),
            move |this: &mut Self, listed, _| {
                if this.generation == generation
                    && let Ok(body) = listed
                {
                    this.installs = body["requests"].as_array().cloned().unwrap_or_default();
                }
            },
        ));
    }

    fn decide_install(&mut self, approve: bool, cx: &mut Context<Self>) {
        let (Some(request), Some(session_id)) = (self.installs.first().cloned(), self.session_id.clone()) else {
            return;
        };
        let id = request["id"].as_str().unwrap_or_default().to_string();
        self.deciding = true;
        let api = api(cx);
        bg::spawn(
            cx,
            move || {
                api.post(
                    &format!("/sessions/{session_id}/skill-installs/{}", encode(&id)),
                    json!({ "decision": if approve { "approve" } else { "deny" } }),
                )
            },
            |this: &mut Self, decided, cx| {
                this.deciding = false;
                this.install_body_open = false;
                if let Err(e) = decided {
                    this.chat.local_notice(format!("Couldn't answer the skill request: {e}"));
                }
                this.load_installs(cx);
            },
        )
        .detach();
        cx.notify();
    }

    fn answer_suggestion(&mut self, accept: bool, cx: &mut Context<Self>) {
        let (Some(suggestion), Some(session_id)) = (self.suggestion.as_mut(), self.session_id.clone()) else { return };
        let data = suggestion.data.clone();
        let pivot = data["source_phase"] == "colony";
        let slug = suggestion.slug.read(cx).value().trim().to_string();
        if accept
            && (slug.is_empty() || !slug.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_'))
        {
            suggestion.error = Some("A colony name uses lowercase letters, digits and _ only.".into());
            cx.notify();
            return;
        }
        suggestion.working = true;
        let queen_id = self.queen.as_ref().map(|q| q.id.clone()).unwrap_or_default();
        let api = api(cx);
        let name = slug.clone();
        bg::spawn(
            cx,
            move || {
                if !accept {
                    return if pivot {
                        api.post(&format!("/sessions/{session_id}/dismiss-colony-pivot"), json!({}))
                    } else {
                        // What the web posts, so the queen hears it was turned down.
                        let original = data["colony_id"].as_str().unwrap_or(&slug);
                        api.post(&format!("/sessions/{session_id}/chat"), json!({ "message": format!("[Dismissed colony suggestion for '{original}'. Continue working in this chat.]"), "display_message": "" }))
                    };
                }
                let mut body = json!({ "colony_id": slug, "source_session_id": session_id, "initial_phase": "colony" });
                if !pivot {
                    body["queen_name"] = json!(queen_id);
                    let goal = data["goal"].as_str().unwrap_or_default();
                    let handoff = data["handoff"].as_str().unwrap_or_default();
                    if !goal.is_empty() || !handoff.is_empty() {
                        body["initial_prompt"] = json!(format!("Goal: {goal}\n\nKnowledge to carry over from the previous chat:\n{handoff}"));
                    }
                }
                api.post("/sessions", body)
            },
            move |this: &mut Self, done, cx| match done {
                Ok(created) => {
                    this.suggestion = None;
                    if accept {
                        let colony = created["colony_id"].as_str().filter(|id| !id.is_empty()).unwrap_or(&name);
                        cx.emit(ChatEvent::Go(Route::Colony(colony.to_string())));
                    }
                }
                Err(e) => {
                    if let Some(s) = this.suggestion.as_mut() {
                        s.working = false;
                        s.error = Some(e.to_string());
                    }
                }
            },
        )
        .detach();
        cx.notify();
    }

    fn stop_worker(&mut self, worker_id: String, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let api = api(cx);
        bg::spawn(
            cx,
            move || api.post(&format!("/sessions/{session_id}/workers/{worker_id}/stop"), json!({})),
            |this: &mut Self, stopped, _| {
                if let Err(e) = stopped {
                    this.chat.local_notice(format!("Couldn't stop the worker: {e}"));
                }
            },
        )
        .detach();
    }

    /// An image a user sent, by its session-relative path, fetched the first time it's asked for.
    fn picture(&mut self, path: &str, cx: &mut Context<Self>) -> Option<Arc<Image>> {
        let session_id = self.session_id.clone()?;
        let file = path.rsplit('/').next().unwrap_or(path);
        self.picture_at(path, format!("/sessions/{session_id}/attachment/{}", encode(file)), cx)
    }

    /// The image the API serves at `api_path`, kept under `key` once fetched.
    fn picture_at(&mut self, key: &str, api_path: String, cx: &mut Context<Self>) -> Option<Arc<Image>> {
        match self.pictures.get(key) {
            Some(Picture::Ready(image)) => return Some(image.clone()),
            Some(_) => return None,
            None => {}
        }
        self.pictures.insert(key.to_string(), Picture::Loading);
        let api = api(cx);
        let key = key.to_string();
        self.tasks.push(bg::spawn(
            cx,
            move || api.bytes(&api_path),
            move |this: &mut Self, bytes, _| {
                let picture = match bytes.ok().and_then(|b| crate::avatars::sniff(&b).map(|format| (format, b))) {
                    Some((format, bytes)) => Picture::Ready(Arc::new(Image::from_bytes(format, bytes))),
                    None => Picture::Failed,
                };
                this.pictures.insert(key, picture);
                // The message holding it grows once the picture is in.
                this.list.remeasure();
            },
        ));
        None
    }

    /// A `chart_*` tool's picture: the PNG it saved, as the web chart's "Download PNG" fetches it.
    fn chart(&mut self, item: &Item, cx: &mut Context<Self>) -> Option<AnyElement> {
        let result: Value = serde_json::from_str(item.detail.result.as_deref()?).ok()?;
        if result["error"].as_str().is_some_and(|e| !e.is_empty()) {
            return None;
        }
        let file = result["file_path"].as_str()?;
        let path = file.strip_prefix("/api").unwrap_or(file);
        let path = if path.starts_with('/') { path.to_string() } else { format!("/{path}") };
        let image = self.picture_at(&format!("chart:{path}"), path, cx);
        let theme = cx.theme();
        Some(
            v_flex()
                .gap_1()
                .child(match image {
                    Some(image) => img(image).max_w(px(720.)).max_h(px(480.)).rounded_md().into_any_element(),
                    None => div().w(px(320.)).h(px(180.)).rounded_md().bg(theme.muted).into_any_element(),
                })
                .when_some(result["title"].as_str().filter(|t| !t.is_empty()).map(str::to_string), |c, t| {
                    c.child(div().text_xs().text_color(theme.muted_foreground).child(t))
                })
                .into_any_element(),
        )
    }

    /// Start a new chat holding this one up to (not including) the user's message at `before`,
    /// or all of it; the web's "Branch" on a message.
    fn branch(&mut self, before: Option<String>, window: &mut Window, cx: &mut Context<Self>) {
        let Some(session_id) = self.session_id.clone() else { return };
        let api = api(cx);
        bg::spawn_in(
            window,
            cx,
            move || api.post(&format!("/sessions/{session_id}/fork"), json!({ "before_input_at": before })),
            |this: &mut Self, forked, window, cx| match forked {
                Ok(body) => match body["session_id"].as_str() {
                    Some(id) => this.open(Opening::Session(id.to_string()), window, cx),
                    None => this.chat.local_notice(format!("The server made no branch: {body}")),
                },
                Err(e) => this.chat.local_notice(format!("Couldn't branch: {e}")),
            },
        )
        .detach();
    }

    /// Small actions under a message: copy, and for the user's own messages, branch from it.
    fn message_actions(&self, item: &Item, cx: &mut Context<Self>) -> AnyElement {
        let text = item.text.clone();
        let copy = Button::new(SharedString::from(format!("{}-copy", item.id)))
            .xsmall()
            .ghost()
            .icon(IconName::Copy)
            .tooltip("Copy")
            .on_click(move |_, _, cx| cx.write_to_clipboard(ClipboardItem::new_string(text.clone())));
        let mut row = h_flex().gap_0p5().opacity(0.6).child(copy);
        if item.kind == Kind::User && !self.is_colony() {
            let before = item.id.strip_prefix("user-input-").map(str::to_string);
            row = row.child(
                Button::new(SharedString::from(format!("{}-branch", item.id)))
                    .xsmall()
                    .ghost()
                    .icon(IconName::GitBranch)
                    .tooltip("New chat from before this message")
                    .on_click(cx.listener(move |this, _, window, cx| this.branch(before.clone(), window, cx))),
            );
        }
        row.into_any_element()
    }

    // ----- Rendering -----

    fn render_header(&mut self, cx: &mut Context<Self>) -> AnyElement {
        let picture = self.queen.as_ref().map(|q| crate::avatars::avatar(q, px(36.), cx));
        let theme = cx.theme().clone();
        let busy = self.chat.busy;
        let (name, sub) = match &self.target {
            Target::Queen(q) => (q.name.clone(), ui::role(&q.title).to_string()),
            // Directory names use `_`; the header reads better with spaces.
            Target::Colony(name) => (
                name.replace('_', " "),
                self.queen.as_ref().map(|q| format!("Colony · led by {}", q.name)).unwrap_or_else(|| "Colony".into()),
            ),
        };
        let title: AnyElement = match &self.renaming {
            Some(input) => h_flex()
                .gap_1()
                .child(div().w(px(260.)).child(Input::new(input).small()))
                .child(
                    Button::new("save-title")
                        .small()
                        .ghost()
                        .icon(IconName::Check)
                        .on_click(cx.listener(|this, _, _, cx| this.save_title(cx))),
                )
                .child(Button::new("cancel-title").small().ghost().icon(IconName::X).on_click(cx.listener(
                    |this, _, _, cx| {
                        this.renaming = None;
                        cx.notify();
                    },
                )))
                .into_any_element(),
            None => h_flex()
                .gap_1()
                .text_xs()
                .text_color(theme.muted_foreground)
                .when(self.is_colony(), |row| row.child(sub.clone()))
                .when_some(self.title.clone(), |row, t| row.child(if self.is_colony() { format!("· {t}") } else { t }))
                .when(self.session_id.is_some(), |row| {
                    row.child(
                        Button::new("rename")
                            .xsmall()
                            .ghost()
                            .icon(IconName::Pencil)
                            .tooltip("Rename this chat")
                            .on_click(cx.listener(|this, _, window, cx| this.start_rename(window, cx))),
                    )
                })
                .into_any_element(),
        };
        h_flex()
            .justify_between()
            .px_5()
            .py_3()
            .border_b_1()
            .border_color(theme.border)
            .child(
                h_flex()
                    .gap_3()
                    .children(picture)
                    .child(
                        v_flex()
                            .child(
                                // Her name opens her profile, as the web header's does.
                                div()
                                    .id("queen-name")
                                    .font_semibold()
                                    .when_some(
                                        self.queen.as_ref().filter(|_| !self.is_colony()).map(|q| q.id.clone()),
                                        |name, id| {
                                            name.cursor_pointer().hover(|s| s.underline()).on_click(cx.listener(
                                                move |_, _, _, cx| cx.emit(ChatEvent::Go(Route::Profile(id.clone()))),
                                            ))
                                        },
                                    )
                                    .child(name),
                            )
                            .child(title),
                    )
                    .when(!self.is_colony() && !sub.is_empty(), |row| row.child(ui::pill(sub.clone(), &theme))),
            )
            .child(
                h_flex()
                    .gap_2()
                    .when_some(self.chat.context_pct, |row, pct| {
                        // Past 80% the server starts compacting; worth a glance before then.
                        let color = if pct >= 80.0 { theme.warning } else { theme.muted_foreground };
                        row.child(div().mr_2().text_xs().text_color(color).child(format!("Context {pct:.0}%")))
                    })
                    .when(busy, |row| {
                        row.child(
                            h_flex()
                                .gap_1p5()
                                .mr_2()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(Spinner::new().small())
                                .child("Thinking…"),
                        )
                        .child(
                            Button::new("stop")
                                .small()
                                .outline()
                                .icon(IconName::Square)
                                .label("Stop")
                                .on_click(cx.listener(|this, _, _, cx| this.stop_turn(cx))),
                        )
                    })
                    .child(
                        Button::new("find")
                            .small()
                            .ghost()
                            .icon(IconName::Search)
                            .tooltip("Find in this chat (Ctrl+F)")
                            .on_click(cx.listener(|this, _, window, cx| this.open_find(window, cx))),
                    )
                    .when(!self.is_colony(), |row| {
                        row.child(
                            Button::new("plan")
                                .small()
                                .ghost()
                                .icon(IconName::ListChecks)
                                .tooltip("Her plan for this chat")
                                .selected(self.plan_open)
                                .on_click(cx.listener(|this, _, _, cx| this.toggle_plan(cx))),
                        )
                        .child(
                            Button::new("new-chat")
                                .small()
                                .ghost()
                                .icon(IconName::SquarePen)
                                .tooltip("New chat")
                                .on_click(cx.listener(|this, _, window, cx| this.open(Opening::New, window, cx))),
                        )
                        .child(
                            Button::new("sessions")
                                .small()
                                .ghost()
                                .icon(IconName::Clock)
                                .tooltip("Her other chats")
                                .selected(self.sessions_open)
                                .on_click(cx.listener(|this, _, _, cx| this.toggle_sessions(cx))),
                        )
                    })
                    .when(self.is_colony(), |row| {
                        row.child(
                            Button::new("panel")
                                .small()
                                .ghost()
                                .icon(IconName::PanelRight)
                                .tooltip("Workers, plan, schedules and data")
                                .selected(self.panel_open)
                                .on_click(cx.listener(|_, _, _, cx| cx.emit(ChatEvent::TogglePanel))),
                        )
                    }),
            )
            .into_any_element()
    }

    fn render_sessions(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme();
        let current = self.session_id.clone();
        let body = match &self.sessions {
            None => v_flex().p_4().child(Spinner::new().small()),
            Some(Err(e)) => v_flex().p_4().child(ui::error_line(e.clone(), theme)),
            Some(Ok(sessions)) if sessions.is_empty() => v_flex().p_4().child(ui::muted("No other chats yet.", theme)),
            Some(Ok(sessions)) => v_flex().gap_0p5().p_2().children(sessions.iter().enumerate().map(|(ix, s)| {
                let active = current.as_deref() == Some(s.session_id.as_str());
                let title = s
                    .title
                    .clone()
                    .filter(|t| !t.is_empty())
                    .or_else(|| s.last_message.clone())
                    .unwrap_or_else(|| "Untitled chat".into());
                let when = s.last_active_at.or(s.created_at).map(ui::ago).unwrap_or_default();
                let id = s.session_id.clone();
                v_flex()
                    .id(("session", ix))
                    .px_3()
                    .py_2()
                    .rounded_md()
                    .cursor_pointer()
                    .when(active, |row| row.bg(theme.list_active))
                    .when(!active, |row| row.hover(|row| row.bg(theme.list_hover)))
                    .child(div().text_sm().truncate().child(ui::clip(&title, 80)))
                    .child(
                        h_flex()
                            .gap_2()
                            .text_xs()
                            .text_color(theme.muted_foreground)
                            .when(s.live, |row| row.child(ui::dot(theme.success)))
                            .child(when)
                            .when_some(s.message_count, |row, n| row.child(format!("· {n} messages"))),
                    )
                    .on_click(
                        cx.listener(move |this, _, window, cx| this.open(Opening::Session(id.clone()), window, cx)),
                    )
            })),
        };
        v_flex()
            .w(px(300.))
            .h_full()
            .flex_shrink_0()
            .border_l_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(div().px_4().py_3().text_sm().font_semibold().child("Chats"))
            .child(div().id("sessions").flex_1().min_h_0().overflow_y_scroll().child(body))
            .into_any_element()
    }

    /// Tell the list which rows changed since it last laid them out.
    fn sync_list(&mut self) {
        let has_older = self.older.is_some();
        let prints: Vec<u64> = self
            .chat
            .items
            .iter()
            .map(|item| {
                let mut h = DefaultHasher::new();
                (
                    &item.kind,
                    &item.text,
                    item.detail.images.len(),
                    item.detail.input.is_some(),
                    item.detail.result.is_some(),
                    self.expanded.contains(&item.id),
                )
                    .hash(&mut h);
                h.finish()
            })
            .collect();
        let offset = has_older as usize;
        let (old, new) = (self.laid_out.len(), prints.len());
        // A different chat (fewer items), older history put in front (a new first item), or the
        // "load earlier" row coming or going all shift the rows, so the list starts over.
        if has_older != self.list_has_older || new < old || (old > 0 && prints[0] != self.laid_out[0]) {
            self.list.reset(new + offset);
        } else {
            for ix in (0..old).filter(|&ix| prints[ix] != self.laid_out[ix]) {
                self.list.remeasure_items(ix + offset..ix + offset + 1);
            }
            if new > old {
                self.list.splice(old + offset..old + offset, new - old);
            }
        }
        self.laid_out = prints;
        self.list_has_older = has_older;
    }

    /// One row of the message list.
    fn render_row(&mut self, ix: usize, cx: &mut Context<Self>) -> AnyElement {
        if self.list_has_older && ix == 0 {
            let button = Button::new("older")
                .small()
                .ghost()
                .loading(self.loading_older)
                .label("Load earlier messages")
                .on_click(cx.listener(|this, _, _, cx| this.load_older(cx)));
            return h_flex().justify_center().pt_4().child(button).into_any_element();
        }
        let item_ix = ix - self.list_has_older as usize;
        let Some(item) = self.chat.items.get(item_ix).cloned() else { return div().into_any_element() };
        let found = self.found(cx) == Some(item_ix);
        let indent = !matches!(item.kind, Kind::User | Kind::Queen);
        let body = self.render_item(&item, cx);
        let ring = cx.theme().ring;
        div()
            .px_6()
            .pt_4()
            .when(indent, |row| row.pl(px(24. + 44.)))
            .child(div().when(found, |d| d.rounded_lg().border_2().border_color(ring).p_1()).child(body))
            .into_any_element()
    }

    fn render_item(&mut self, item: &Item, cx: &mut Context<Self>) -> AnyElement {
        let toggle = {
            let id = item.id.clone();
            cx.listener(move |this, _: &ClickEvent, _, cx| this.toggle_expanded(&id, cx))
        };
        let images: Vec<Option<Arc<Image>>> = item.detail.images.iter().map(|p| self.picture(p, cx)).collect();
        let actions = self.message_actions(item, cx);
        let chart = match &item.kind {
            Kind::Tool { name, state: ToolState::Done } if name.starts_with("chart_") => self.chart(item, cx),
            _ => None,
        };
        let open = self.expanded.contains(&item.id);
        match &item.kind {
            Kind::User => {
                let theme = cx.theme();
                v_flex()
                    .items_end()
                    .gap_1()
                    .when(!images.is_empty(), |col| {
                        col.child(h_flex().gap_1().children(images.into_iter().map(|image| match image {
                            Some(image) => img(image).max_w(px(240.)).max_h(px(240.)).rounded_md().into_any_element(),
                            None => div().size(px(96.)).rounded_md().bg(theme.muted).into_any_element(),
                        })))
                    })
                    .when(!item.text.is_empty(), |col| {
                        let bubble = div()
                            .max_w(px(640.))
                            .px_4()
                            .py_2p5()
                            .rounded_xl()
                            .border_1()
                            .border_color(theme.primary.opacity(0.22))
                            .bg(theme.primary.opacity(0.09))
                            .text_color(theme.foreground);
                        col.child(match qa_pairs(&item.text) {
                            // Answers to several questions read as a list, as on the web.
                            Some(pairs) => bubble.child(v_flex().gap_1().children(pairs.into_iter().map(|(q, a)| {
                                v_flex()
                                    .child(div().text_xs().text_color(theme.muted_foreground).child(q))
                                    .child(div().child(a))
                            }))),
                            None => bubble.child(item.text.clone()),
                        })
                    })
                    .child(h_flex().gap_2().child(actions).when(!item.time().is_empty(), |row| {
                        row.child(div().text_xs().text_color(theme.muted_foreground).child(item.time().to_string()))
                    }))
                    .into_any_element()
            }
            Kind::Queen => match model_error(&item.text) {
                Some(error) => self.render_model_error(&item.id, error, open, cx),
                None => {
                    let face = self.queen.clone().map(|q| crate::avatars::avatar(&q, px(32.), cx));
                    let (name, title) =
                        self.queen.as_ref().map(|q| (q.name.clone(), q.title.clone())).unwrap_or_default();
                    let theme = cx.theme();
                    h_flex()
                        .items_start()
                        .gap_3()
                        .child(div().w(px(32.)).flex_shrink_0().children(face))
                        .child(
                            v_flex()
                                .flex_1()
                                .min_w_0()
                                .gap_1p5()
                                .child(
                                    h_flex()
                                        .gap_2()
                                        .when(!name.is_empty(), |row| {
                                            row.child(
                                                div().text_sm().font_medium().text_color(theme.primary).child(name),
                                            )
                                        })
                                        .when(!title.is_empty(), |row| row.child(ui::pill(title, theme)))
                                        .when(!item.time().is_empty(), |row| {
                                            row.child(
                                                div()
                                                    .text_xs()
                                                    .text_color(theme.muted_foreground)
                                                    .child(item.time().to_string()),
                                            )
                                        }),
                                )
                                .child(
                                    div()
                                        .max_w(px(820.))
                                        .px_4()
                                        .py_3()
                                        .rounded_xl()
                                        .border_1()
                                        .border_color(theme.primary.opacity(0.18))
                                        .bg(theme.primary.opacity(0.05))
                                        .child(ui::markdown(
                                            SharedString::from(item.id.clone()),
                                            item.text.clone(),
                                            theme,
                                        )),
                                )
                                .child(actions),
                        )
                        .into_any_element()
                }
            },
            Kind::Question => {
                let theme = cx.theme();
                h_flex()
                    .max_w(px(820.))
                    .gap_2()
                    .items_start()
                    .child(Icon::new(IconName::MessageCircleQuestionMark).small().text_color(theme.primary))
                    .child(div().text_sm().font_medium().child(item.text.clone()))
                    .into_any_element()
            }
            Kind::Thinking => {
                let theme = cx.theme();
                let text = if open { item.text.clone() } else { ui::clip(&item.text, THINKING_PREVIEW) };
                div()
                    .id(SharedString::from(item.id.clone()))
                    .max_w(px(820.))
                    .pl_3()
                    .border_l_2()
                    .border_color(theme.border)
                    .text_xs()
                    .text_color(theme.muted_foreground)
                    .cursor_pointer()
                    .child(text)
                    .on_click(toggle)
                    .into_any_element()
            }
            Kind::Tool { name, state } => v_flex()
                .gap_2()
                .child(render_tool(item, name, *state, open, cx.theme(), toggle))
                .children(chart)
                .into_any_element(),
            Kind::Worker { id } => self.render_worker(&item.id, id, open, toggle, cx),
            Kind::Notice => {
                let theme = cx.theme();
                div()
                    .max_w(px(820.))
                    .px_3()
                    .py_2()
                    .rounded_md()
                    .bg(theme.muted)
                    .text_sm()
                    .child(item.text.clone())
                    .into_any_element()
            }
        }
    }

    fn render_model_error(&self, id: &str, error: &str, open: bool, cx: &mut Context<Self>) -> AnyElement {
        let toggle = {
            let id = id.to_string();
            cx.listener(move |this, _: &ClickEvent, _, cx| this.toggle_expanded(&id, cx))
        };
        let settings = cx.listener(|_, _: &ClickEvent, _, cx| cx.emit(ChatEvent::Go(Route::Page(Page::Models))));
        let theme = cx.theme();
        let why = if is_key_problem(error) {
            "Its API key is missing or was rejected."
        } else {
            "The provider returned an error."
        };
        v_flex()
            .max_w(px(640.))
            .gap_2()
            .p_3()
            .rounded_lg()
            .border_1()
            .border_color(theme.danger)
            .child(
                h_flex()
                    .gap_2()
                    .child(Icon::new(IconName::TriangleAlert).small().text_color(theme.danger))
                    .child(div().text_sm().font_medium().child("The model couldn't reply.")),
            )
            .child(div().text_sm().text_color(theme.muted_foreground).child(why))
            .child(
                h_flex()
                    .gap_2()
                    .child(
                        Button::new(SharedString::from(format!("{id}-settings")))
                            .small()
                            .outline()
                            .label("Model settings")
                            .on_click(settings),
                    )
                    .child(
                        Button::new(SharedString::from(format!("{id}-details")))
                            .small()
                            .ghost()
                            .label(if open { "Hide details" } else { "Details" })
                            .on_click(toggle),
                    ),
            )
            .when(open, |col| {
                col.child(
                    div()
                        .text_xs()
                        .font_family("monospace")
                        .text_color(theme.muted_foreground)
                        .child(error.to_string()),
                )
            })
            .into_any_element()
    }

    fn render_worker(
        &self,
        item_id: &str,
        worker_id: &str,
        open: bool,
        toggle: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let worker = self.workers.get(worker_id).cloned().unwrap_or(Value::Null);
        let status = worker["status"].as_str().unwrap_or("").to_string();
        let running = matches!(status.as_str(), "pending" | "running" | "claimed" | "in_progress");
        let stop = {
            let id = worker_id.to_string();
            cx.listener(move |this, _: &ClickEvent, _, cx| this.stop_worker(id.clone(), cx))
        };
        let theme = cx.theme();
        let (label, color) = match status.as_str() {
            _ if running => ("running", theme.warning),
            "completed" | "done" => ("completed", theme.success),
            "failed" => ("failed", theme.danger),
            "" => ("starting", theme.muted_foreground),
            _ => ("stopped", theme.muted_foreground),
        };
        let text_of = |v: &Value| v.as_str().unwrap_or_default().to_string();
        let goal = Some(text_of(&worker["goal"])).filter(|g| !g.is_empty()).unwrap_or_else(|| text_of(&worker["task"]));
        let summary = text_of(&worker["result"]["summary"]);
        let progress = worker["task_summary"]["total"]
            .as_i64()
            .filter(|t| *t > 0)
            .map(|t| format!("{}/{t} tasks", worker["task_summary"]["completed"].as_i64().unwrap_or(0)));
        let short: String = worker_id.chars().take(8).collect();
        v_flex()
            .id(SharedString::from(item_id.to_string()))
            .max_w(px(820.))
            .gap_1()
            .px_3()
            .py_2()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .cursor_pointer()
            .on_click(toggle)
            .child(
                h_flex()
                    .justify_between()
                    .child(
                        h_flex()
                            .gap_2()
                            .child(Icon::new(IconName::Bot).small().text_color(theme.muted_foreground))
                            .child(div().text_sm().font_medium().child(format!("Worker {short}")))
                            .child(h_flex().gap_1().text_xs().text_color(color).child(ui::dot(color)).child(label))
                            .when_some(progress, |row, p| {
                                row.child(div().text_xs().text_color(theme.muted_foreground).child(p))
                            }),
                    )
                    .when(running, |row| {
                        row.child(
                            Button::new(SharedString::from(format!("{item_id}-stop")))
                                .xsmall()
                                .ghost()
                                .label("Stop")
                                .on_click(stop),
                        )
                    }),
            )
            .when(!goal.is_empty(), |col| {
                col.child(div().text_sm().child(ui::clip(&goal, if open { 4000 } else { 200 })))
            })
            .when(!summary.is_empty(), |col| {
                col.child(
                    div()
                        .text_sm()
                        .text_color(theme.muted_foreground)
                        .child(ui::clip(&summary, if open { 4000 } else { 200 })),
                )
            })
            .when(open, |col| {
                let result = &worker["result"];
                let mut facts = Vec::new();
                if let Some(secs) = result["duration_seconds"].as_f64() {
                    facts.push(format!("{secs:.0}s"));
                }
                if let Some(tokens) = result["tokens_used"].as_i64() {
                    facts.push(format!("{tokens} tokens"));
                }
                if let Some(calls) = result["tool_calls_used"].as_i64() {
                    facts.push(format!("{calls} tool calls"));
                }
                col.when(!facts.is_empty(), |col| {
                    col.child(div().text_xs().text_color(theme.muted_foreground).child(facts.join(" · ")))
                })
                .when_some(result["error"].as_str().filter(|e| !e.is_empty()).map(str::to_string), |col, e| {
                    col.child(div().text_xs().text_color(theme.danger).child(e))
                })
            })
            .into_any_element()
    }

    fn render_questions(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        let form = self.questions.as_ref()?;
        let ready = self.answers(cx);
        let single = self.chat.pending.len() == 1;
        let theme = cx.theme().clone();
        let mut col = v_flex().gap_3().p_3().rounded_lg().border_1().border_color(theme.primary);
        if !single {
            col = col.child(
                div()
                    .text_xs()
                    .text_color(theme.muted_foreground)
                    .child(format!("{} questions", self.chat.pending.len())),
            );
        }
        for (qx, question) in self.chat.pending.iter().enumerate() {
            let picked = form.picked[qx].clone();
            let mut options = h_flex().gap_2().flex_wrap();
            for (ox, option) in question.options.iter().enumerate() {
                let chosen = picked.as_deref() == Some(option.as_str());
                let value = option.clone();
                options = options.child(
                    Button::new(("answer", qx * 100 + ox))
                        .small()
                        .outline()
                        .selected(chosen)
                        .label(format!("{}. {option}", ox + 1))
                        .on_click(
                            cx.listener(move |this, _, window, cx| this.pick_answer(qx, value.clone(), window, cx)),
                        ),
                );
            }
            col = col.child(
                v_flex()
                    .gap_2()
                    .when(!single, |c| c.child(div().text_sm().font_medium().child(question.prompt.clone())))
                    .when(!question.options.is_empty(), |c| c.child(options))
                    .child(Input::new(&form.others[qx]).small()),
            );
        }
        let send = cx.listener(|this, _, window, cx| {
            if let Some(answers) = this.answers(cx) {
                this.submit_answers(answers, window, cx);
            }
        });
        Some(
            col.child(
                h_flex().justify_end().child(
                    Button::new("send-answers")
                        .small()
                        .primary()
                        .label(if single { "Send answer" } else { "Send answers" })
                        .disabled(ready.is_none())
                        .on_click(send),
                ),
            )
            .into_any_element(),
        )
    }

    fn render_cards(&self, cx: &mut Context<Self>) -> Vec<AnyElement> {
        let theme = cx.theme().clone();
        let mut cards = Vec::new();
        if let Some(form) = &self.credential {
            let title = form.data["title"]
                .as_str()
                .filter(|t| !t.is_empty())
                .unwrap_or("The queen needs a credential")
                .to_string();
            let instructions = form.data["instructions"].as_str().unwrap_or_default().to_string();
            cards.push(
                v_flex()
                    .gap_2()
                    .p_3()
                    .rounded_lg()
                    .border_1()
                    .border_color(theme.primary)
                    .child(
                        h_flex()
                            .gap_2()
                            .child(Icon::new(IconName::KeyRound).small())
                            .child(div().text_sm().font_medium().child(title)),
                    )
                    .when(!instructions.is_empty(), |c| {
                        c.child(div().text_sm().text_color(theme.muted_foreground).child(instructions))
                    })
                    .children(form.fields.iter().map(|(_, label, input)| {
                        v_flex()
                            .gap_1()
                            .child(div().text_xs().text_color(theme.muted_foreground).child(label.clone()))
                            .child(Input::new(input).small().mask_toggle())
                    }))
                    .child(
                        div()
                            .text_xs()
                            .text_color(theme.muted_foreground)
                            .child("Stored encrypted. The agent never sees these values."),
                    )
                    .when_some(form.error.clone(), |c, e| c.child(ui::error_line(e, &theme)))
                    .child(
                        h_flex()
                            .gap_2()
                            .justify_end()
                            .child(
                                Button::new("cred-cancel")
                                    .small()
                                    .ghost()
                                    .label("Cancel")
                                    .on_click(cx.listener(|this, _, _, cx| this.answer_credential(false, cx))),
                            )
                            .child(
                                Button::new("cred-save")
                                    .small()
                                    .primary()
                                    .label("Save")
                                    .loading(form.saving)
                                    .on_click(cx.listener(|this, _, _, cx| this.answer_credential(true, cx))),
                            ),
                    )
                    .into_any_element(),
            );
        }
        if let Some(request) = self.installs.first() {
            let name = request["name"].as_str().unwrap_or_default().to_string();
            let body = request["body"].as_str().unwrap_or_default().to_string();
            let files: Vec<String> = request["files"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|f| f["path"].as_str().map(str::to_string))
                .collect();
            let who = self.queen.as_ref().map(|q| q.name.clone()).unwrap_or_else(|| "The queen".into());
            cards.push(
                v_flex()
                    .gap_2()
                    .p_3()
                    .rounded_lg()
                    .border_1()
                    .border_color(theme.primary)
                    .child(
                        h_flex().gap_2().child(Icon::new(IconName::Sparkles).small()).child(
                            div().text_sm().font_medium().child(format!(
                                "{who} wants to install the skill \"{name}\" for every queen and colony"
                            )),
                        ),
                    )
                    .when(self.installs.len() > 1, |c| {
                        c.child(
                            div()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(format!("1 of {}", self.installs.len())),
                        )
                    })
                    .child(
                        div()
                            .text_sm()
                            .text_color(theme.muted_foreground)
                            .child(request["description"].as_str().unwrap_or_default().to_string()),
                    )
                    .when(request["replaces"].as_bool().unwrap_or(false), |c| {
                        c.child(
                            div().text_sm().text_color(theme.warning).child("This replaces a skill of the same name."),
                        )
                    })
                    .when(!files.is_empty(), |c| {
                        c.child(
                            div()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(format!("Files: {}", files.join(", "))),
                        )
                    })
                    .when(self.install_body_open, |c| {
                        c.child(
                            div()
                                .id("install-body")
                                .max_h(px(320.))
                                .overflow_y_scroll()
                                .p_2()
                                .rounded_md()
                                .bg(theme.muted)
                                .child(ui::markdown("install-body-md", body, &theme)),
                        )
                    })
                    .child(
                        h_flex()
                            .gap_2()
                            .justify_end()
                            .child(
                                Button::new("install-body")
                                    .small()
                                    .ghost()
                                    .label(if self.install_body_open { "Hide SKILL.md" } else { "Show SKILL.md" })
                                    .on_click(cx.listener(|this, _, _, cx| {
                                        this.install_body_open = !this.install_body_open;
                                        cx.notify();
                                    })),
                            )
                            .child(
                                Button::new("install-deny")
                                    .small()
                                    .outline()
                                    .label("Deny")
                                    .loading(self.deciding)
                                    .on_click(cx.listener(|this, _, _, cx| this.decide_install(false, cx))),
                            )
                            .child(
                                Button::new("install-approve")
                                    .small()
                                    .primary()
                                    .label("Install")
                                    .loading(self.deciding)
                                    .on_click(cx.listener(|this, _, _, cx| this.decide_install(true, cx))),
                            ),
                    )
                    .into_any_element(),
            );
        }
        if let Some(s) = &self.suggestion {
            let reason = s.data["reason"].as_str().or(s.data["goal"].as_str()).unwrap_or_default().to_string();
            cards.push(
                v_flex()
                    .gap_2()
                    .p_3()
                    .rounded_lg()
                    .border_1()
                    .border_color(theme.primary)
                    .child(
                        h_flex()
                            .gap_2()
                            .child(Icon::new(IconName::Network).small())
                            .child(div().text_sm().font_medium().child("Start a colony for this?")),
                    )
                    .when(!reason.is_empty(), |c| {
                        c.child(div().text_sm().text_color(theme.muted_foreground).child(reason))
                    })
                    .when_some(s.data["task_count"].as_i64().filter(|n| *n > 0), |c, n| {
                        c.child(
                            div()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(format!("{n} tasks will be seeded")),
                        )
                    })
                    .child(div().w(px(280.)).child(Input::new(&s.slug).small()))
                    .when_some(s.error.clone(), |c, e| c.child(ui::error_line(e, &theme)))
                    .child(
                        h_flex()
                            .gap_2()
                            .justify_end()
                            .child(
                                Button::new("colony-no")
                                    .small()
                                    .ghost()
                                    .label("Not now")
                                    .on_click(cx.listener(|this, _, _, cx| this.answer_suggestion(false, cx))),
                            )
                            .child(
                                Button::new("colony-yes")
                                    .small()
                                    .primary()
                                    .label("Create colony")
                                    .loading(s.working)
                                    .on_click(cx.listener(|this, _, _, cx| this.answer_suggestion(true, cx))),
                            ),
                    )
                    .into_any_element(),
            );
        }
        cards
    }

    fn render_composer(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let chips = self.attachments.iter().enumerate().map(|(ix, a)| {
            // Removed by name, not place: two quick clicks mustn't drop the wrong file.
            let name = a.name.clone();
            h_flex()
                .gap_1()
                .pl_2()
                .rounded_md()
                .bg(theme.muted)
                .text_xs()
                .child(Icon::new(IconName::Paperclip).xsmall())
                .child(a.name.clone())
                .child(Button::new(("unattach", ix)).xsmall().ghost().icon(IconName::X).on_click(cx.listener(
                    move |this, _, _, cx| {
                        if let Some(at) = this.attachments.iter().position(|a| a.name == name) {
                            this.attachments.remove(at);
                        }
                        cx.notify();
                    },
                )))
        });
        // A white card holding the words, as the web composer is: attachments above, actions below.
        v_flex()
            .gap_2()
            .px_3()
            .pt_2()
            .pb_2()
            .rounded_xl()
            .border_1()
            .border_color(theme.border)
            .bg(theme.popover)
            .when(!self.attachments.is_empty(), |col| col.child(h_flex().gap_2().flex_wrap().children(chips)))
            .child(Textarea::new(&self.composer).appearance(false))
            .child(
                h_flex()
                    .justify_between()
                    .child(
                        h_flex()
                            .gap_1()
                            .child(
                                Button::new("attach")
                                    .small()
                                    .ghost()
                                    .icon(IconName::Paperclip)
                                    .tooltip("Attach images or files (or drop or paste them)")
                                    .loading(self.attaching)
                                    .on_click(cx.listener(|this, _, _, cx| this.attach(cx))),
                            )
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(theme.muted_foreground)
                                    .child("Enter sends · Shift+Enter for a new line"),
                            ),
                    )
                    .child(
                        Button::new("send")
                            .small()
                            .primary()
                            .icon(IconName::ArrowUp)
                            .tooltip("Send")
                            .on_click(cx.listener(|this, _, window, cx| this.send(window, cx))),
                    ),
            )
            .into_any_element()
    }
}

/// A tool call's one-line pill, opening to what it was given and gave back.
fn render_tool(
    item: &Item,
    name: &str,
    state: ToolState,
    open: bool,
    theme: &Theme,
    toggle: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
) -> AnyElement {
    let (icon, color) = match state {
        ToolState::Running => (Spinner::new().small().into_any_element(), theme.muted_foreground),
        ToolState::Done => (Icon::new(IconName::Check).small().into_any_element(), theme.success),
        ToolState::Failed => (Icon::new(IconName::CircleX).small().into_any_element(), theme.danger),
    };
    v_flex()
        .max_w(px(820.))
        .child(
            h_flex()
                .id(SharedString::from(item.id.clone()))
                .gap_1p5()
                .text_xs()
                .text_color(color)
                .cursor_pointer()
                .child(icon)
                .child(div().text_color(theme.muted_foreground).child(name.to_string()))
                .child(
                    Icon::new(if open { IconName::ChevronDown } else { IconName::ChevronRight })
                        .xsmall()
                        .text_color(theme.muted_foreground),
                )
                .on_click(toggle),
        )
        .when(open, |col| {
            let detail = v_flex().mt_1().gap_2().p_3().rounded_md().bg(theme.muted).text_xs().font_family("monospace");
            col.child(match terminal_detail(name, item) {
                Some((command, output, meta)) => detail
                    .child(div().font_semibold().child(format!("$ {command}")))
                    .when(!output.is_empty(), |c| c.child(ui::clip(&output, 4000)))
                    .when(!meta.is_empty(), |c| c.child(div().text_color(theme.muted_foreground).child(meta))),
                None => detail
                    .when_some(item.detail.input.clone(), |col, input| {
                        col.child(div().text_color(theme.muted_foreground).child("Input")).child(input)
                    })
                    .when_some(item.detail.result.clone(), |col, result| {
                        col.child(div().text_color(theme.muted_foreground).child("Result"))
                            .child(ui::clip(&result, 4000))
                    }),
            })
        })
        .into_any_element()
}

/// A `terminal_*` call as a shell reads: (command, stdout then stderr, "exit 1 · 230 ms"), as
/// `TerminalToolDetail.tsx` shows it; `None` for any other tool or an input without a command.
fn terminal_detail(name: &str, item: &Item) -> Option<(String, String, String)> {
    if !name.starts_with("terminal_") {
        return None;
    }
    let input: Value = serde_json::from_str(item.detail.input.as_deref()?).ok()?;
    let command = input["command"].as_str().or(input["cmd"].as_str())?.to_string();
    let result: Value = item.detail.result.as_deref().and_then(|r| serde_json::from_str(r).ok()).unwrap_or(Value::Null);
    let stdout = result["stdout"].as_str().or(result["output"].as_str()).unwrap_or_default();
    let stderr = result["stderr"].as_str().unwrap_or_default();
    let output = match (stdout.is_empty(), stderr.is_empty()) {
        (_, true) => stdout.to_string(),
        (true, false) => format!("[stderr]\n{stderr}"),
        (false, false) => format!("{stdout}\n\n[stderr]\n{stderr}"),
    };
    let mut meta = Vec::new();
    if let Some(code) = result["exit_code"].as_i64() {
        meta.push(format!("exit {code}"));
    }
    if let Some(ms) = result["runtime_ms"].as_i64() {
        meta.push(format!("{ms} ms"));
    }
    if result["timed_out"].as_bool().unwrap_or(false) {
        meta.push("timed out".into());
    }
    Some((command, output, meta.join(" · ")))
}

impl Render for ChatView {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        self.sync_questions(window, cx);
        self.sync_list();
        let header = self.render_header(cx);
        let find = self.render_find(cx);
        let cards = self.render_cards(cx);
        let bottom = self.render_questions(cx).unwrap_or_else(|| self.render_composer(cx));
        let sessions = self.sessions_open.then(|| self.render_sessions(cx));
        let plan = self.plan_open.then(|| {
            let theme = cx.theme();
            v_flex()
                .w(px(320.))
                .h_full()
                .flex_shrink_0()
                .border_l_1()
                .border_color(theme.border)
                .bg(theme.sidebar)
                .child(div().px_4().py_3().text_sm().font_semibold().child("Plan"))
                .child(
                    div()
                        .id("plan")
                        .flex_1()
                        .min_h_0()
                        .overflow_y_scroll()
                        .px_4()
                        .pb_4()
                        .child(crate::plan::render(&self.plan, theme)),
                )
        });
        let rows = list(self.list.clone(), cx.processor(|this, ix: usize, _, cx| this.render_row(ix, cx))).size_full();
        let theme = cx.theme();
        let messages = div().flex_1().min_h_0().pb_3().child(rows);
        let chat = v_flex()
            .flex_1()
            .h_full()
            .min_w_0()
            .when_some(self.status.clone(), |col, status| {
                col.child(
                    div().px_5().py_1p5().text_xs().text_color(theme.muted_foreground).bg(theme.muted).child(status),
                )
            })
            .child(messages)
            .child(
                v_flex().gap_2().px_5().py_3().border_t_1().border_color(theme.border).children(cards).child(bottom),
            );
        let drop_tint = cx.theme().drop_target;
        v_flex()
            .size_full()
            .key_context("ChatView")
            .on_action(cx.listener(|this, _: &Find, window, cx| this.open_find(window, cx)))
            // Before the composer's own paste: an image or files become attachments, text pastes as usual.
            .capture_action(cx.listener(|this, _: &Paste, _, cx| {
                if this.paste_attachments(cx) {
                    cx.stop_propagation();
                }
            }))
            .drag_over::<ExternalPaths>(move |style, _, _, _| style.bg(drop_tint))
            .on_drop(cx.listener(|this, paths: &ExternalPaths, _, cx| this.attach_paths(paths.paths().to_vec(), cx)))
            .child(header)
            .children(find)
            .child(h_flex().flex_1().min_h_0().child(chat).children(sessions).children(plan))
    }
}

/// Keep a session's event stream open: reconnect when it drops, resume the session when it stopped.
fn stream_loop(api: &Api, session_id: &str, resume: &Resume, stop: &AtomicBool, tx: &smol::channel::Sender<Feed>) {
    const FIRST_RETRY: Duration = Duration::from_secs(1);
    const LAST_RETRY: Duration = Duration::from_secs(15);
    let path = format!("/sessions/{session_id}/events");
    let mut delay = FIRST_RETRY;
    // A session found not running is resumed at first and after the connection itself failed (the
    // server restarted), once each time. After the server closed the stream cleanly it was stopped,
    // or its colony deleted or renamed, on purpose; resuming then would bring it back.
    let mut may_resume = true;
    while !stop.load(Ordering::Relaxed) {
        let mut connected = false;
        let ended = api.stream(&path, stop, |event| {
            if !connected {
                connected = true;
                delay = FIRST_RETRY;
                if tx.send_blocking(Feed::Connected).is_err() {
                    return false;
                }
            }
            tx.send_blocking(Feed::Event(event)).is_ok()
        });
        let problem = match ended {
            Ok(StreamEnd::Stopped) => return,
            Ok(StreamEnd::Closed) => {
                may_resume = false;
                "The event stream closed; reconnecting…".to_string()
            }
            Ok(StreamEnd::NotLive) if !may_resume => {
                tx.send_blocking(Feed::Ended).ok();
                return;
            }
            Ok(StreamEnd::NotLive) => {
                may_resume = false;
                let resumed = match resume {
                    Resume::Queen(queen_id) => api.resume(session_id, queen_id),
                    Resume::Colony(colony) => api.resume_colony(session_id, colony),
                };
                match resumed {
                    Ok(()) => {
                        // The session is back; there's nothing to wait out before reading it.
                        if tx.send_blocking(Feed::Problem("Resumed the session; reconnecting…".into())).is_err() {
                            return;
                        }
                        delay = FIRST_RETRY;
                        continue;
                    }
                    Err(e) => format!("Couldn't resume the session: {e}"),
                }
            }
            Err(e) => {
                may_resume = true;
                format!("Lost the event stream ({e}); reconnecting…")
            }
        };
        if tx.send_blocking(Feed::Problem(problem)).is_err() {
            return;
        }
        std::thread::sleep(delay);
        delay = (delay * 2).min(LAST_RETRY);
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::{is_key_problem, model_error, qa_pairs, terminal_detail};
    use crate::chat::{Detail, Item, Kind, ToolState};

    #[test]
    fn reads_a_terminal_call_as_command_output_and_exit() {
        let item = Item {
            id: "tool-x-1".into(),
            kind: Kind::Tool { name: "terminal_exec".into(), state: ToolState::Done },
            text: String::new(),
            at: String::new(),
            detail: Detail {
                input: Some(r#"{"command": "ls data"}"#.into()),
                result: Some(r#"{"stdout": "a.csv", "stderr": "warn", "exit_code": 0, "runtime_ms": 12}"#.into()),
                images: Vec::new(),
            },
        };
        let (command, output, meta) = terminal_detail("terminal_exec", &item).unwrap();

        assert_eq!(command, "ls data");
        assert_eq!(output, "a.csv\n\n[stderr]\nwarn");
        assert_eq!(meta, "exit 0 · 12 ms");
        assert!(terminal_detail("web_search", &item).is_none());
    }

    #[test]
    fn reads_answers_to_several_questions_as_pairs() {
        let pairs = qa_pairs("\"Which city?\"=\"Oslo\"\n\"When?\"=\"Friday\"").unwrap();
        assert_eq!(
            pairs,
            vec![("Which city?".to_string(), "Oslo".to_string()), ("When?".to_string(), "Friday".to_string())]
        );
        assert_eq!(qa_pairs("\"Which city?\"=\"Oslo\""), None);
        assert_eq!(qa_pairs("just words"), None);
    }

    #[test]
    fn spots_a_failed_model_call_and_a_key_problem() {
        let text = "[Error: LLM call failed: AuthenticationError: invalid x-api-key. Please try again.]";
        assert_eq!(model_error(text), Some("AuthenticationError: invalid x-api-key"));
        assert!(is_key_problem(model_error(text).unwrap()));
        assert_eq!(model_error("All good."), None);
        assert!(!is_key_problem("rate limited (429)"));
    }
}
