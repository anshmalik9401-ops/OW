
require("dotenv").config();

// Google DNS configuration - MongoDB SRV fix
const dns = require("dns");
dns.setServers(["8.8.8.8", "8.8.4.4"]);

const express = require("express");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const app = express();

const PORT = Number(process.env.PORT) || 5000;
const ADMIN_TOKEN = process.env.ADMIN_TOKEN || "";
const MONGODB_URI = process.env.MONGODB_URI || "";
const DB_NAME = process.env.MONGODB_DB || "licenses";
const DATA_FILE = process.env.DATA_FILE || path.join(__dirname, "licenses.json");


if (ADMIN_TOKEN.length < 32) {
    console.error("ADMIN_TOKEN must be at least 32 characters.");
    process.exit(1);
}

if (!MONGODB_URI && process.env.NODE_ENV === "production") {
    console.error("MONGODB_URI required in production.");
    process.exit(1);
}

app.disable("x-powered-by");
app.set("trust proxy", 1);
app.use(express.json({ limit: "10kb" }));

// ---------------- DATABASE ----------------

function fileStore() {
    let db = { keys: [], config: {} };

    if (fs.existsSync(DATA_FILE)) {
        db = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));
    }

    const save = () => {
        const temp = DATA_FILE + ".tmp";
        fs.writeFileSync(temp, JSON.stringify(db, null, 2));
        fs.renameSync(temp, DATA_FILE);
    };

    return {
        async getConfig(name) {
            return db.config[name] || null;
        },

        async setConfig(name, value) {
            db.config[name] = value;
            save();
        },

        async findKey(key) {
            return db.keys.find(k => k.key === key) || null;
        },

        async listKeys() {
            return [...db.keys].sort((a, b) => b.createdAt - a.createdAt);
        },

        async insertKey(doc) {
            if (db.keys.some(k => k.key === doc.key)) {
                throw new Error("Duplicate license key");
            }
            db.keys.push(doc);
            save();
        },

        async updateKey(key, patch) {
            const i = db.keys.findIndex(k => k.key === key);
            if (i < 0) return null;
            db.keys[i] = { ...db.keys[i], ...patch };
            save();
            return db.keys[i];
        },

        async deleteKey(key) {
            const old = db.keys.length;
            db.keys = db.keys.filter(k => k.key !== key);
            save();
            return db.keys.length < old;
        }
    };
}

async function mongoStore(uri) {
    const { MongoClient } = require("mongodb");

    const client = new MongoClient(uri, {
        serverSelectionTimeoutMS: 10000
    });

    await client.connect();

    const db = client.db(DB_NAME);
    const keys = db.collection("keys");
    const config = db.collection("config");

    await keys.createIndex({ key: 1 }, { unique: true });

    const clean = doc => {
        if (!doc) return null;
        const { _id, ...rest } = doc;
        return rest;
    };

    return {
        async getConfig(name) {
            const doc = await config.findOne({ _id: name });
            return doc ? doc.value : null;
        },

        async setConfig(name, value) {
            await config.updateOne(
                { _id: name },
                { $set: { value } },
                { upsert: true }
            );
        },

        async findKey(key) {
            return clean(await keys.findOne({ key }));
        },

        async listKeys() {
            return (await keys.find({})
                .sort({ createdAt: -1 })
                .toArray()).map(clean);
        },

        async insertKey(doc) {
            await keys.insertOne(doc);
        },

        async updateKey(key, patch) {
            await keys.updateOne({ key }, { $set: patch });
            return clean(await keys.findOne({ key }));
        },

        async deleteKey(key) {
            const result = await keys.deleteOne({ key });
            return result.deletedCount > 0;
        }
    };
}

// ---------------- SIGNING KEYS ----------------

async function loadSigningKeys(store) {
    let pem = await store.getConfig("signingPrivateKey");

    if (!pem) {
        const pair = crypto.generateKeyPairSync("ed25519");

        pem = pair.privateKey.export({
            type: "pkcs8",
            format: "pem"
        });

        await store.setConfig("signingPrivateKey", pem);
    }

    const privateKey = crypto.createPrivateKey(pem);
    const publicKey = crypto.createPublicKey(privateKey);

    const der = publicKey.export({
        type: "spki",
        format: "der"
    });

    return {
        privateKey,
        publicKeyB64: der.subarray(-32).toString("base64")
    };
}

// ---------------- HELPERS ----------------

function newKey() {
    const part = () => crypto.randomBytes(3).toString("hex").toUpperCase();

    return `LIC-${part()}-${part()}-${part()}-${part()}`;
}

function safeEqual(a, b) {
    const x = Buffer.from(String(a));
    const y = Buffer.from(String(b));

    return x.length === y.length && crypto.timingSafeEqual(x, y);
}

function publicView(k) {
    const now = Date.now();

    return {
        key: k.key,
        label: k.label,
        blocked: !!k.blocked,
        expiresAt: k.expiresAt,
        expired: !!(k.expiresAt && k.expiresAt < now),
        maxDevices: k.maxDevices,
        devices: k.devices || [],
        createdAt: k.createdAt,
        lastSeen: k.lastSeen || null
    };
}

function asyncRoute(fn) {
    return (req, res, next) => {
        Promise.resolve(fn(req, res, next)).catch(next);
    };
}

// ---------------- SERVER ----------------

async function main() {
    const store = MONGODB_URI
        ? await mongoStore(MONGODB_URI)
        : fileStore();

    const { privateKey, publicKeyB64 } =
        await loadSigningKeys(store);

    // Rate limiting
    const hits = new Map();

    function limited(ip) {
        const now = Date.now();

        if (hits.size > 10000) {
            for (const [address, times] of hits) {
                if (!times.length || now - times[times.length - 1] > 60000) {
                    hits.delete(address);
                }
            }
        }

        const list = (hits.get(ip) || [])
            .filter(t => now - t < 60000);

        list.push(now);
        hits.set(ip, list);

        return list.length > 30;
    }

    function sign(payload) {
        const text = JSON.stringify(payload);

        const sig = crypto.sign(
            null,
            Buffer.from(text, "utf8"),
            privateKey
        ).toString("base64");

        return { payload: text, sig };
    }

    function admin(req, res, next) {
        const header = req.headers.authorization || "";
        const token = header.startsWith("Bearer ")
            ? header.slice(7)
            : "";

        if (!safeEqual(token, ADMIN_TOKEN)) {
            return res.status(401).json({
                error: "Unauthorized"
            });
        }

        next();
    }

    // Public endpoints

    app.get("/", (req, res) => {
        res.type("text").send("License server running");
    });

    app.get("/health", (req, res) => {
        res.json({ ok: true });
    });

    app.get("/api/public-key", (req, res) => {
        res.json({ publicKey: publicKeyB64 });
    });

    // License verification

    app.post("/api/verify", asyncRoute(async (req, res) => {
        if (limited(req.ip)) {
            return res.status(429).json({
                ok: false,
                reason: "Too many requests"
            });
        }

        const { key, device, nonce } = req.body || {};

        if (![key, device, nonce].every(
            v => typeof v === "string" &&
            v.length > 0 &&
            v.length < 200
        )) {
            return res.status(400).json({
                ok: false,
                reason: "Invalid request"
            });
        }

        const rec = await store.findKey(key.trim());

        const deny = reason => res.json({
            ok: false,
            reason
        });

        if (!rec) return deny("License key galat hai");
        if (rec.blocked) return deny("License blocked hai");

        const now = Date.now();

        if (rec.expiresAt && rec.expiresAt < now) {
            return deny("License expire ho gaya");
        }

        const devices = rec.devices || [];

        if (!devices.includes(device)) {
            if (devices.length >= (rec.maxDevices || 1)) {
                return deny("License dusre computer par already use ho raha hai");
            }

            devices.push(device);
        }

        await store.updateKey(rec.key, {
            devices,
            lastSeen: now
        });

        return res.json({
            ok: true,
            ...sign({
                key: rec.key,
                device,
                nonce,
                ts: now,
                expiresAt: rec.expiresAt || null
            })
        });
    }));

    // Admin APIs

    app.get("/api/admin/keys", admin, asyncRoute(async (req, res) => {
        res.json((await store.listKeys()).map(publicView));
    }));

    app.post("/api/admin/keys", admin, asyncRoute(async (req, res) => {
        const { label, days, maxDevices } = req.body || {};

        const d = Number(days);
        const devices = Number(maxDevices) || 1;

        if (!Number.isFinite(d) || d < 0 || d > 3650) {
            return res.status(400).json({
                error: "Invalid expiry days"
            });
        }

        if (!Number.isInteger(devices) || devices < 1 || devices > 50) {
            return res.status(400).json({
                error: "Invalid device limit"
            });
        }

        const doc = {
            key: newKey(),
            label: String(label || "").slice(0, 80),
            blocked: false,
            expiresAt: d > 0 ? Date.now() + d * 86400000 : null,
            maxDevices: devices,
            devices: [],
            createdAt: Date.now(),
            lastSeen: null
        };

        await store.insertKey(doc);

        res.json(publicView(doc));
    }));

    app.post("/api/admin/keys/:key/block", admin, asyncRoute(async (req, res) => {
        const k = await store.updateKey(req.params.key, {
            blocked: true
        });

        k ? res.json(publicView(k))
          : res.status(404).json({ error: "Key not found" });
    }));

    app.post("/api/admin/keys/:key/unblock", admin, asyncRoute(async (req, res) => {
        const k = await store.updateKey(req.params.key, {
            blocked: false
        });

        k ? res.json(publicView(k))
          : res.status(404).json({ error: "Key not found" });
    }));

    app.post("/api/admin/keys/:key/extend", admin, asyncRoute(async (req, res) => {
        const rec = await store.findKey(req.params.key);

        if (!rec) {
            return res.status(404).json({ error: "Key not found" });
        }

        const d = Number((req.body || {}).days);

        if (!Number.isInteger(d) || d < 1 || d > 3650) {
            return res.status(400).json({ error: "Invalid days" });
        }

        const base = rec.expiresAt && rec.expiresAt > Date.now()
            ? rec.expiresAt
            : Date.now();

        const updated = await store.updateKey(rec.key, {
            expiresAt: base + d * 86400000
        });

        res.json(publicView(updated));
    }));

    app.post("/api/admin/keys/:key/no-expiry", admin, asyncRoute(async (req, res) => {
        const k = await store.updateKey(req.params.key, {
            expiresAt: null
        });

        k ? res.json(publicView(k))
          : res.status(404).json({ error: "Key not found" });
    }));

    app.post("/api/admin/keys/:key/reset-devices", admin, asyncRoute(async (req, res) => {
        const k = await store.updateKey(req.params.key, {
            devices: []
        });

        k ? res.json(publicView(k))
          : res.status(404).json({ error: "Key not found" });
    }));

    app.delete("/api/admin/keys/:key", admin, asyncRoute(async (req, res) => {
        const deleted = await store.deleteKey(req.params.key);

        deleted
            ? res.json({ ok: true })
            : res.status(404).json({ error: "Key not found" });
    }));

    // Admin panel

    const adminPage = path.join(__dirname, "admin.html");

    app.get("/admin", (req, res) => {
        if (!fs.existsSync(adminPage)) {
            return res.status(404).send("admin.html not found");
        }

        res.sendFile(adminPage);
    });

    // Error handler

    app.use((err, req, res, next) => {
        console.error("API error:", err);

        if (res.headersSent) return next(err);

        res.status(500).json({
            error: "Internal server error"
        });
    });

    app.listen(PORT, () => {
        console.log(`License server running on port ${PORT}`);
        console.log(`Storage: ${MONGODB_URI ? "MongoDB" : "Local file"}`);
        console.log(`PUBLIC KEY: ${publicKeyB64}`);
    });
}

main().catch(error => {
    console.error("Server startup failed:", error);
    process.exit(1);
});
