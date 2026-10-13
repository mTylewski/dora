// Encrypted local storage on the lawyer's computer (IndexedDB in the browser).
// Every record is encrypted with AES-GCM; the key is derived from the lawyer's password (PBKDF2-SHA-256)
// and exists only in memory while the app is unlocked. Without the password the stored data is unreadable;
// a forgotten password cannot be recovered (by design) - the encrypted backup file uses the same password.

const DB_NAME = "claims-vault";
const DB_VERSION = 1;
const ITERATIONS = 600_000;
const VERIFIER = "claims-vault-ok";

export interface Profile { name: string; email: string }
interface Sealed { iv: string; data: string } // base64
interface AccountMeta { salt: string; iterations: number; verifier: Sealed; createdAt: string }
interface StoredRecord { key: string; kind: string; id: string; updatedAt: string; iv: string; data: string }

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64(bytes: ArrayBuffer | Uint8Array): string {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000));
  return btoa(s);
}
function unb64(s: string): Uint8Array<ArrayBuffer> {
  const bin = atob(s);
  const u8 = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta");
      if (!db.objectStoreNames.contains("records")) {
        const store = db.createObjectStore("records", { keyPath: "key" });
        store.createIndex("kind", "kind");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(db: IDBDatabase, store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const req = fn(db.transaction(store, mode).objectStore(store));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function deriveKey(password: string, salt: Uint8Array<ArrayBuffer>, iterations: number): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

async function seal(key: CryptoKey, bytes: Uint8Array<ArrayBuffer>): Promise<Sealed> {
  const iv = crypto.getRandomValues(new Uint8Array(new ArrayBuffer(12)));
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, bytes);
  return { iv: b64(iv), data: b64(data) };
}

async function open(key: CryptoKey, sealed: Sealed): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(sealed.iv) }, key, unb64(sealed.data)));
}

export class Vault {
  private constructor(private db: IDBDatabase, private key: CryptoKey) {}

  static async exists(): Promise<boolean> {
    const db = await openDb();
    const meta = await tx<AccountMeta | undefined>(db, "meta", "readonly", (s) => s.get("account"));
    db.close();
    return !!meta;
  }

  static async create(password: string, profile: Profile): Promise<Vault> {
    if (password.length < 10) throw new Error("Hasło musi mieć co najmniej 10 znaków.");
    const db = await openDb();
    if (await tx(db, "meta", "readonly", (s) => s.get("account"))) {
      db.close();
      throw new Error("Konto już istnieje na tym komputerze.");
    }
    const salt = crypto.getRandomValues(new Uint8Array(new ArrayBuffer(16)));
    const key = await deriveKey(password, salt, ITERATIONS);
    const meta: AccountMeta = { salt: b64(salt), iterations: ITERATIONS, verifier: await seal(key, enc.encode(VERIFIER)), createdAt: new Date().toISOString() };
    await tx(db, "meta", "readwrite", (s) => s.put(meta, "account"));
    const vault = new Vault(db, key);
    await vault.put("profile", "me", profile);
    return vault;
  }

  /** null when the password is wrong. */
  static async unlock(password: string): Promise<Vault | null> {
    const db = await openDb();
    const meta = await tx<AccountMeta | undefined>(db, "meta", "readonly", (s) => s.get("account"));
    if (!meta) {
      db.close();
      throw new Error("Brak konta na tym komputerze.");
    }
    const key = await deriveKey(password, unb64(meta.salt), meta.iterations);
    let ok = false;
    try {
      ok = dec.decode(await open(key, meta.verifier)) === VERIFIER;
    } catch {
      ok = false;
    }
    if (!ok) {
      db.close(); // a wrong password must not keep the database open
      return null;
    }
    return new Vault(db, key);
  }

  lock(): void {
    this.db.close();
    (this as unknown as { key: CryptoKey | null }).key = null;
  }

  async put(kind: string, id: string, value: unknown): Promise<void> {
    await this.putBytes(kind, id, enc.encode(JSON.stringify(value)));
  }

  async get<T>(kind: string, id: string): Promise<T | null> {
    const bytes = await this.getBytes(kind, id);
    return bytes ? (JSON.parse(dec.decode(bytes)) as T) : null;
  }

  async putBytes(kind: string, id: string, bytes: Uint8Array<ArrayBuffer>): Promise<void> {
    const sealed = await seal(this.key, bytes);
    const record: StoredRecord = { key: `${kind}:${id}`, kind, id, updatedAt: new Date().toISOString(), ...sealed };
    await tx(this.db, "records", "readwrite", (s) => s.put(record));
  }

  async getBytes(kind: string, id: string): Promise<Uint8Array | null> {
    const record = await tx<StoredRecord | undefined>(this.db, "records", "readonly", (s) => s.get(`${kind}:${id}`));
    return record ? open(this.key, record) : null;
  }

  async list<T>(kind: string): Promise<{ id: string; updatedAt: string; value: T }[]> {
    const records = await tx<StoredRecord[]>(this.db, "records", "readonly", (s) => s.index("kind").getAll(kind));
    return Promise.all(records.map(async (r) => ({
      id: r.id, updatedAt: r.updatedAt, value: JSON.parse(dec.decode(await open(this.key, r))) as T,
    })));
  }

  async delete(kind: string, id: string): Promise<void> {
    await tx(this.db, "records", "readwrite", (s) => s.delete(`${kind}:${id}`));
  }

  /** Delete all records whose key starts with `${kind}:${prefix}` (e.g. all PDFs of a case). */
  async deletePrefix(kind: string, prefix: string): Promise<void> {
    const records = await tx<StoredRecord[]>(this.db, "records", "readonly", (s) => s.index("kind").getAll(kind));
    for (const r of records) if (r.id.startsWith(prefix)) await this.delete(kind, r.id);
  }

  /** Encrypted backup: the records stay encrypted, the same password opens them. */
  async exportBackup(): Promise<Blob> {
    const meta = await tx<AccountMeta>(this.db, "meta", "readonly", (s) => s.get("account"));
    const records = await tx<StoredRecord[]>(this.db, "records", "readonly", (s) => s.getAll());
    const payload = { format: "claims-vault-backup", version: 1, exportedAt: new Date().toISOString(), meta, records };
    return new Blob([JSON.stringify(payload)], { type: "application/octet-stream" });
  }

  /** Restore a backup on this computer (replaces local data). Returns false when the password does not open it. */
  static async importBackup(text: string, password: string): Promise<boolean> {
    const payload = JSON.parse(text) as { format: string; meta: AccountMeta; records: StoredRecord[] };
    if (payload.format !== "claims-vault-backup") throw new Error("To nie jest plik kopii zapasowej.");
    const key = await deriveKey(password, unb64(payload.meta.salt), payload.meta.iterations);
    try {
      if (dec.decode(await open(key, payload.meta.verifier)) !== VERIFIER) return false;
    } catch {
      return false;
    }
    const db = await openDb();
    await tx(db, "records", "readwrite", (s) => s.clear());
    for (const r of payload.records) await tx(db, "records", "readwrite", (s) => s.put(r));
    await tx(db, "meta", "readwrite", (s) => s.put(payload.meta, "account"));
    db.close();
    return true;
  }

  /** Remove the account and all data from this computer. */
  static async destroy(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const req = indexedDB.deleteDatabase(DB_NAME);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
      req.onblocked = () => resolve();
    });
  }
}
