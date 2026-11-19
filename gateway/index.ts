/**
 * Cổng link cố định cho "Video chuyển đổi Tiếng Việt" (tạo bởi Ngô Thị Hồng Hạnh).
 *
 * Máy chủ xử lý video chạy trên Google Colab với link tạm (…trycloudflare.com, đổi mỗi lần chạy).
 * Colab tự gửi link tạm về cổng này (POST /__register); cổng chuyển tiếp mọi truy cập sang đó.
 * Nhờ vậy web và ứng dụng Android chỉ cần MỘT link cố định: https://<tên-worker>.<tài-khoản>.workers.dev
 */
import { DurableObject } from "cloudflare:workers";

export interface Env {
  BACKEND: DurableObjectNamespace<Backend>;
  REGISTER_TOKEN?: string; // Secret: mã bí mật để Colab đăng ký link (đặt trong Cloudflare)
}

/** Lưu link máy chủ hiện tại (bộ nhớ bền của Cloudflare, miễn phí). */
export class Backend extends DurableObject<Env> {
  async getInfo(): Promise<{ url: string | null; at: number | null }> {
    return {
      url: (await this.ctx.storage.get<string>("url")) ?? null,
      at: (await this.ctx.storage.get<number>("at")) ?? null,
    };
  }
  async setUrl(url: string): Promise<void> {
    await this.ctx.storage.put("url", url);
    await this.ctx.storage.put("at", Date.now());
  }
}

const TUNNEL_DOWN = new Set([502, 503, 504, 520, 521, 522, 523, 524, 530]);

function sameSecret(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function offline(req: Request, reason: string, at: number | null): Response {
  const path = new URL(req.url).pathname;
  if (path.startsWith("/api/")) {
    return Response.json({ detail: "Máy chủ xử lý đang tắt. Mở Google Colab và chạy ô 1 → 4." }, { status: 503 });
  }
  const when = at ? new Date(at).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "chưa có";
  const html = `<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Máy chủ đang tắt</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#e8eaf0;
font:15px/1.55 system-ui,-apple-system,Roboto,sans-serif;padding:16px}.box{max-width:420px;width:100%;background:#171a21;
border:1px solid #2a2f3a;border-radius:16px;padding:22px}.logo{width:56px;height:56px;border-radius:16px;
background:linear-gradient(135deg,#ff2e4d,#ff7a45);display:grid;place-items:center;font-weight:800;margin:0 auto 10px}
h1{font-size:18px;text-align:center;margin:0}.by{text-align:center;color:#8b93a7;font-size:13px}.by b{color:#f4c710}
.msg{background:#f4c71022;color:#f8de6b;border-radius:10px;padding:10px 12px;margin-top:14px;font-size:14px}
ol{padding-left:20px;color:#c9cfdc;font-size:14px}button{width:100%;background:#ff2e4d;border:0;color:#fff;border-radius:10px;
padding:12px;font:inherit;font-weight:700;margin-top:6px}.muted{color:#8b93a7;font-size:12px;text-align:center;margin-top:10px}</style>
</head><body><div class="box"><div class="logo">中→V</div><h1>Video chuyển đổi Tiếng Việt</h1>
<div class="by">Được tạo bởi <b>Ngô Thị Hồng Hạnh</b></div>
<div class="msg">⏸ Máy chủ xử lý video đang tắt (${reason}).</div>
<ol><li>Mở notebook <b>colab_run_web.ipynb</b> trên Google Colab.</li><li>Chạy lần lượt ô 1 → 4.</li>
<li>Quay lại đây bấm <b>Thử lại</b>. <b>Link này giữ nguyên</b>, không cần đổi.</li></ol>
<button onclick="location.reload()">🔄 Thử lại</button>
<div class="muted">Lần cuối máy chủ báo link: ${when}<br>Trang tự thử lại sau 20 giây.</div></div>
<script>setTimeout(()=>location.reload(),20000)</script></body></html>`;
  // trả 200 để ứng dụng Android hiển thị trang này (không coi là lỗi)
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const store = env.BACKEND.get(env.BACKEND.idFromName("main"));

    // Colab báo link tạm mới
    if (url.pathname === "/__register" && req.method === "POST") {
      if (!env.REGISTER_TOKEN) return Response.json({ ok: false, error: "Chưa đặt Secret REGISTER_TOKEN trên Cloudflare" }, { status: 500 });
      let body: { url?: string; token?: string };
      try { body = await req.json(); } catch { return Response.json({ ok: false, error: "Dữ liệu không hợp lệ" }, { status: 400 }); }
      if (!body.token || !sameSecret(body.token, env.REGISTER_TOKEN)) return Response.json({ ok: false, error: "Sai mã REGISTER_TOKEN" }, { status: 403 });
      let target: URL;
      try { target = new URL(body.url ?? ""); } catch { return Response.json({ ok: false, error: "Link không hợp lệ" }, { status: 400 }); }
      if (target.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(target.hostname)) {
        return Response.json({ ok: false, error: "Link phải là https" }, { status: 400 });
      }
      await store.setUrl(target.origin);
      return Response.json({ ok: true, backend: target.origin });
    }

    const info = await store.getInfo();
    if (url.pathname === "/__status") {
      return Response.json({ backend_set: !!info.url, updated: info.at });
    }
    if (!info.url) return offline(req, "chưa có máy chủ nào kết nối", null);

    // chuyển tiếp nguyên vẹn sang máy chủ Colab (kể cả tải video lên / tải video về)
    const target = info.url + url.pathname + url.search;
    const headers = new Headers(req.headers);
    headers.set("x-forwarded-host", url.host);
    headers.set("x-forwarded-proto", "https");
    let resp: Response;
    try {
      resp = await fetch(target, {
        method: req.method,
        headers,
        body: req.method === "GET" || req.method === "HEAD" ? undefined : req.body,
        redirect: "manual",
      });
    } catch {
      return offline(req, "không kết nối được", info.at);
    }
    if (TUNNEL_DOWN.has(resp.status) && (resp.headers.get("server") ?? "").includes("cloudflare")) {
      return offline(req, `lỗi ${resp.status}`, info.at);
    }
    const out = new Response(resp.body, resp);
    const loc = out.headers.get("location");
    if (loc && loc.startsWith(info.url)) out.headers.set("location", loc.slice(info.url.length) || "/");
    return out;
  },
} satisfies ExportedHandler<Env>;
