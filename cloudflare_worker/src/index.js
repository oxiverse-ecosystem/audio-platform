/**
 * Cloudflare Worker: signed-URL gate in front of the R2 bucket of variant segments.
 *
 * This enforces exactly the same contract as `audio_streaming.storage.verify_object_url`
 * and the local `/v1/cdn` development endpoint: HMAC-SHA256 over "<key>\n<exp>", base64url
 * without padding. Segments are immutable and shared by all listeners, so once a request is
 * authorized the response is cached at the edge forever and subsequent listeners are served
 * without touching R2 or the origin.
 *
 * Bindings required:
 *   BUCKET          R2 bucket containing assets/<asset_id>/v<0|1>/<seq>.ts
 *   SIGNING_SECRET   secret, must equal the origin's AUDIO_CAPABILITY_SECRET
 */

const encoder = new TextEncoder();
let cachedKey = null;

async function signingKey(secret) {
  if (cachedKey === null) {
    cachedKey = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
  }
  return cachedKey;
}

function base64UrlNoPad(buffer) {
  let binary = "";
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) {
    difference |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return difference === 0;
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405 });
    }
    const url = new URL(request.url);
    const objectKey = decodeURIComponent(url.pathname.replace(/^\/+/, ""));
    const expires = Number(url.searchParams.get("exp"));
    const signature = url.searchParams.get("sig");

    if (!objectKey || !signature || !Number.isFinite(expires)) {
      return new Response("missing signature parameters", { status: 403 });
    }
    if (expires < Math.floor(Date.now() / 1000)) {
      return new Response("expired object signature", { status: 403 });
    }
    if (!/^assets\/[A-Za-z0-9_-]{3,96}\/v[01]\/\d{6}\.ts$/.test(objectKey)) {
      return new Response("invalid object key", { status: 403 });
    }

    const expected = base64UrlNoPad(
      await crypto.subtle.sign("HMAC", await signingKey(env.SIGNING_SECRET), encoder.encode(`${objectKey}\n${expires}`)),
    );
    if (!constantTimeEqual(signature, expected)) {
      return new Response("invalid object signature", { status: 403 });
    }

    // Cache on the immutable object key only -- never on the per-listener signature, or every
    // listener would miss the cache and the whole A/B design would collapse back to origin load.
    const cache = caches.default;
    const cacheKey = new Request(`${url.origin}/${objectKey}`, { method: "GET" });
    const cached = await cache.match(cacheKey);
    if (cached) return cached;

    const object = await env.BUCKET.get(objectKey);
    if (object === null) return new Response("object not found", { status: 404 });

    const response = new Response(object.body, {
      headers: {
        "Content-Type": "video/MP2T",
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": object.httpEtag,
      },
    });
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  },
};
