# Design Research Notes

This MVP separates **access control**, **transport confidentiality**, and **forensic attribution**. These controls are complementary: a signed URL restricts request access, HLS AES-128 protects delivered segments, and a session-specific watermark supports post-incident attribution. Neither signed URLs nor segment encryption prevent analog capture, and no watermark claim is made beyond the controlled tests included with this codebase.

| Topic | Design consequence | Source |
| --- | --- | --- |
| HLS AES-128 | Each media segment uses AES-128-CBC with PKCS#7 padding; the playlist must declare an `EXT-X-KEY` URI and IV. CBC restarts at segment boundaries, so the implementation derives a unique deterministic IV per sequence number. | [RFC 8216](https://datatracker.ietf.org/doc/html/rfc8216) |
| Signed playback links | The session URL carries only an expiring, signed capability. The server rechecks its session record, user identity, expiry, and entitlement on every playlist/segment/key request; it never treats a bearer link as proof of authorization by itself. | [Mux, Signed URLs for Secure Playback](https://www.mux.com/articles/securing-video-playback-with-signed-urls) |
| Localized watermarking | Research systems can target low-latency/localized detection, but the cited AudioSeal implementation is neural. This MVP deliberately uses a compact keyed DSP watermark to avoid a model runtime. It does not inherit AudioSeal’s robustness claims. | [AudioSeal repository](https://github.com/facebookresearch/audioseal) |

## Deployment assessment

| Approach | Trade-offs | Cost | Setup complexity |
| --- | --- | --- | --- |
| Managed request service with this MVP | Suitable for a bounded demonstration or low-throughput VOD path. The 1 vCPU / 512 MiB envelope makes per-session DSP personalization and on-demand media preparation deliberately capped. | Managed-service usage costs | Low |
| Container platform with autoscaling workers and object storage/CDN | Recommended production topology. It moves reusable source intermediates and encrypted personalized segments to object storage, keeps session/audit data in a managed database, and horizontally scales API/DSP workers with explicit per-pod CPU/memory limits. | Provider-dependent | Medium |
| Dedicated media-transcoding fleet | Appropriate for high concurrency, multiple renditions, live streaming, or full forensic-watermark validation. Requires operation of a job queue, worker autoscaling, monitoring, and key-management integration. | Highest | High |

The implemented service is the second option’s **application core**, runnable locally with Python. A production deployment should place it behind TLS termination, managed secrets, a database, object storage, a CDN that preserves authorization behavior, and a queue/worker tier sized from load testing. The managed project host is not claimed as a high-scale media-transcoding platform.

## Security decisions

The service derives a non-reversible 32-bit attribution identifier with HMAC-SHA-256 over the user, asset, and session identifiers. It stores the secure server-side mapping needed for attribution; it does not log the encryption key or watermark secret. The watermark carrier seed is separately derived from the server secret and session context, and is never serialized in a response, playlist, or key endpoint.

Source assets are normalized once to a fixed PCM profile and aligned to segment boundaries. Personalization applies a stateful overlap-add watermark pipeline over each segment sequence so the carrier phase and smoothing envelope continue across boundaries. Segment encryption occurs only after personalization.

## Explicit non-claims

This work intentionally withdraws all earlier Pd/Pfa, AUC, and codec/TSM robustness figures. The automated tests prove API behavior, deterministic controlled-fixture recovery, encryption/key authorization, and boundary continuity only. They do not validate imperceptibility, acoustic replay, TSM resilience, resistance to attacks, or a deployment false-alarm rate. Those require a separately locked corpus, threat-constrained attack suite, and held-out statistical evaluation.

