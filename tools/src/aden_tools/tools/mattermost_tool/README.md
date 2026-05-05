# Musik 🎵

A music streaming app built with React Native (Expo) and TypeScript, powered by the JioSaavn API.

---

## Setup

### Prerequisites
- Node.js 18+
- Expo CLI: `npm install -g expo-cli`
- Android device or emulator (or iOS simulator on Mac)

### Install & Run

```bash
git clone <repo-url>
cd Musik
npm install
npx expo start
```

Scan the QR code with the Expo Go app, or press `a` for Android emulator / `i` for iOS simulator.

### Build APK

```bash
npx expo build:android
# or with EAS
eas build --platform android --profile preview
```

---

## Architecture

```
src/
├── components/          # Reusable UI (MiniPlayer, SongItem, option sheets)
├── context/             # ThemeContext (dark/light mode)
├── hooks/               # usePlayer, useSetupPlayer, useDownload
├── navigation/          # AppNavigator (Stack) + BottomTabNavigator
├── screens/             # Home, Player, Search, Queue, Favorites, Playlists, Downloads, Artist, Album
├── services/            # api.ts (JioSaavn), trackPlayerService.ts (expo-av), downloadService.ts
├── store/               # Zustand stores: playerStore, playlistStore, favoriteStore
└── utils/               # helpers.ts (parseSong, parseArtist, parseAlbum, formatDuration)
```

### State Management — Zustand

Three stores, each persisted to AsyncStorage:

- **playerStore** — current song, queue, queueIndex, shuffle, repeat, playback state. Persisted as `player_state_v1`.
- **playlistStore** — user-created playlists with songs. Persisted as `mume_playlists_v1`.
- **favoriteStore** — liked songs. Persisted as `mume_favorites_v1`.

### Audio — expo-av

`trackPlayerService.ts` manages a single `Audio.Sound` instance with a generation counter to prevent race conditions when songs change quickly. Position and duration are tracked via internal refs and a custom listener system — avoiding Zustand updates on every 500ms tick and keeping the seek bar smooth with zero unnecessary re-renders.

### Navigation — React Navigation v6

Stack navigator wrapping a bottom tab navigator. Player opens as a `fullScreenModal` with a slide-up animation. MiniPlayer sits above the tab bar on every tab screen.

---

## Features

### Core
- **Home** — Suggested/Songs/Artists/Albums tabs, infinite scroll pagination, sort options
- **Search** — Live search across songs, artists, albums with recent search history
- **Full Player** — Artwork, seek bar, play/pause, prev/next, ±10s skip, shuffle, repeat (none/all/one), favorites, options sheet
- **Mini Player** — Persistent bar across all tabs, perfectly synced with full player
- **Queue** — Add, reorder (drag), remove songs; queue count badge on tab icon; persisted across sessions
- **Favorites** — Heart any song from any screen; persisted locally
- **Playlists** — Create, rename, delete playlists; add/remove songs
- **Downloads** — Save songs for reference; shuffle play downloaded songs
- **Artist / Album screens** — Browse songs and albums by artist, full album tracklists

### Bonus
- Shuffle mode with random queue traversal
- Repeat modes: off → repeat all → repeat one
- Download songs (metadata saved to AsyncStorage; plays from CDN URL)
- Dark / Light theme toggle
- Session restore — last played song reloads on app launch, ready to play immediately

---

## Trade-offs & Known Limitations

**Download is CDN-backed, not truly offline.** `downloadService.ts` saves song metadata locally so the Downloads screen persists across sessions, but audio still streams from the JioSaavn CDN URL. True offline playback would require `expo-file-system` to download the `.mp4` to device storage. This was skipped to avoid the complexity of managing local file paths across OS versions and the EAS build configuration it requires.

**API host fallback.** Three JioSaavn mirror hosts are tried in sequence if a request fails. This improves reliability but adds latency on failover.

**Lyrics, Speed, Timer, Cast** buttons are present in the UI but not functional — the JioSaavn API doesn't provide lyrics data, and the other controls were scoped out for time.

**Folders tab** shows an empty state — device file system access requires `expo-media-library` permissions which are out of scope for a streaming app.

---

## Extra Features Added Beyond Requirements

- Recent search history with per-item and clear-all controls
- Song options sheet available from every screen (Home, Search, Queue, Artist, Album, Player)
- Add to playlist flow with inline create-new-playlist option
- Queue badge showing live song count on the tab bar
- Drag-to-reorder queue rows
- Per-session audio state restore (mini player and audio loaded on cold start)
- API retry logic across 3 mirror hosts
- Optimistic play/pause UI (no waiting for audio status callbacks)

---

## Tech Stack

| | |
|---|---|
| Framework | React Native (Expo SDK 51) |
| Language | TypeScript |
| Navigation | React Navigation v6 — Native Stack + Bottom Tabs |
| State | Zustand |
| Storage | AsyncStorage |
| Audio | expo-av |
| API | JioSaavn (saavn.sumit.co) |
