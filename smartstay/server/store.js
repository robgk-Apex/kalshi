// Tiny JSON-backed data store with debounced persistence.
// Zero native dependencies — reliable in any Node 18+ environment.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, 'data');
const DB_FILE = path.join(DATA_DIR, 'db.json');

const EMPTY = {
  users: [],
  listings: [],
  bookings: [],
  reviews: [],
  favorites: [], // { userId, listingId }
  messages: [],  // { id, listingId, threadId, fromId, toId, body, createdAt, read }
  meta: { seeded: false },
};

let db = structuredClone(EMPTY);
let saveTimer = null;

export function load() {
  try {
    if (fs.existsSync(DB_FILE)) {
      const raw = fs.readFileSync(DB_FILE, 'utf8');
      db = { ...structuredClone(EMPTY), ...JSON.parse(raw) };
    }
  } catch (err) {
    console.error('Failed to load db, starting fresh:', err.message);
    db = structuredClone(EMPTY);
  }
  return db;
}

export function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      fs.mkdirSync(DATA_DIR, { recursive: true });
      fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
    } catch (err) {
      console.error('Failed to save db:', err.message);
    }
  }, 50);
}

// Force a synchronous save (used by seeder / graceful shutdown).
export function flush() {
  clearTimeout(saveTimer);
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
  } catch (err) {
    console.error('Failed to flush db:', err.message);
  }
}

export function getDb() {
  return db;
}

export function id() {
  return (globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2) + Date.now().toString(36));
}
