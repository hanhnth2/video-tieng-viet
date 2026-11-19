package com.ngothihonghanh.videoviet;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Ứng dụng "Video Tiếng Việt" — được tạo bởi Ngô Thị Hồng Hạnh.
 * Bảng điều khiển trên điện thoại cho máy chủ xử lý video (Google Colab / VPS).
 */
public class MainActivity extends Activity {
    private static final String PREFS = "cfg";
    private static final String KEY_SERVER = "server";
    private static final int REQ_FILE = 1;
    private static final String SETUP = "file:///android_asset/setup.html";

    private WebView web;
    private Button doneBtn;
    private boolean loginMode = false;
    private ValueCallback<Uri[]> fileCallback;
    private String pendingLink;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(0xFF0F1115);
        getWindow().setNavigationBarColor(0xFF0F1115);

        web = new WebView(this);
        web.setBackgroundColor(0xFF0F1115);
        FrameLayout root = new FrameLayout(this);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        // nút hiện khi đang đăng nhập Xiaohongshu trong app
        doneBtn = new Button(this);
        doneBtn.setText("✓ Đã đăng nhập xong – lưu và quay lại");
        doneBtn.setTextColor(0xFFFFFFFF);
        doneBtn.setAllCaps(false);
        doneBtn.setBackgroundColor(0xFFFF2E4D);
        doneBtn.setVisibility(View.GONE);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
        int m = (int) (12 * getResources().getDisplayMetrics().density);
        lp.setMargins(m, m, m, m);
        root.addView(doneBtn, lp);
        doneBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                finishXhsLogin();
            }
        });
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setUserAgentString(s.getUserAgentString() + " VideoVietApp/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);

        web.addJavascriptInterface(new Bridge(), "Android");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener(new Downloader());

        handleIntent(getIntent());
        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            start();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
        if (pendingLink != null && !server().isEmpty()) {
            String url = web.getUrl();
            if (url != null && url.startsWith(server())) {
                // trang đã mở: điền link trực tiếp
                web.evaluateJavascript("window.setLink && setLink(" + JSONObject.quote(pendingLink) + ")", null);
                pendingLink = null;
            } else {
                start();
            }
        }
    }

    @Override
    public void onBackPressed() {
        if (loginMode) {
            finishXhsLogin();
            return;
        }
        if (web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    // ---------------------------------------------------------------- điều hướng
    private String server() {
        return getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, "");
    }

    private void start() {
        String srv = server();
        if (srv.isEmpty()) {
            showSetup(null);
            return;
        }
        String url = srv + "/";
        if (pendingLink != null) {
            url += "?link=" + enc(pendingLink);
            pendingLink = null;
        }
        web.loadUrl(url);
    }

    private void showSetup(String message) {
        String q = "?cur=" + enc(server()) + (message != null ? "&msg=" + enc(message) : "");
        if (pendingLink != null) q += "&link=" + enc(pendingLink);
        web.loadUrl(SETUP + q);
    }

    // ---------------------------------------------------------------- đăng nhập Xiaohongshu trong app
    private void startXhsLogin() {
        loginMode = true;
        doneBtn.setVisibility(View.VISIBLE);
        Toast.makeText(this, "Đăng nhập tài khoản Xiaohongshu, xong bấm nút đỏ ở dưới", Toast.LENGTH_LONG).show();
        web.loadUrl("https://www.xiaohongshu.com/explore");
    }

    private static boolean isXhs(String url) {
        return url.contains("xiaohongshu.com") || url.contains("rednote.com") || url.contains("xhscdn.com")
                || url.contains("xhslink.com");
    }

    private void finishXhsLogin() {
        loginMode = false;
        doneBtn.setVisibility(View.GONE);
        CookieManager cm = CookieManager.getInstance();
        cm.flush();
        StringBuilder sb = new StringBuilder();
        String[] hosts = {"https://www.xiaohongshu.com", "https://edith.xiaohongshu.com", "https://www.rednote.com"};
        java.util.LinkedHashMap<String, String> map = new java.util.LinkedHashMap<String, String>();
        for (String h : hosts) {
            String c = cm.getCookie(h);
            if (c == null) continue;
            for (String part : c.split(";")) {
                int i = part.indexOf('=');
                if (i > 0) map.put(part.substring(0, i).trim(), part.substring(i + 1).trim());
            }
        }
        for (java.util.Map.Entry<String, String> e : map.entrySet()) {
            if (sb.length() > 0) sb.append("; ");
            sb.append(e.getKey()).append('=').append(e.getValue());
        }
        final String cookie = sb.toString();
        if (!map.containsKey("web_session")) {
            Toast.makeText(this, "Chưa thấy phiên đăng nhập. Hãy đăng nhập xong rồi bấm lại.", Toast.LENGTH_LONG).show();
            start();
            return;
        }
        final String srv = server();
        final String userAgent = web.getSettings().getUserAgentString();
        new Thread(new Runnable() {
            public void run() {
                String msg;
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(srv + "/api/settings/xhs_cookie").openConnection();
                    c.setRequestMethod("POST");
                    c.setDoOutput(true);
                    c.setConnectTimeout(15000);
                    c.setReadTimeout(20000);
                    c.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
                    c.setRequestProperty("User-Agent", userAgent);   // tránh Cloudflare chặn (lỗi 1010)
                    String auth = CookieManager.getInstance().getCookie(srv);   // phiên đăng nhập mật khẩu của web
                    if (auth != null) c.setRequestProperty("Cookie", auth);
                    OutputStream os = c.getOutputStream();
                    os.write(("cookie=" + enc(cookie)).getBytes("UTF-8"));
                    os.close();
                    int code = c.getResponseCode();
                    msg = code == 200 ? "Đã lưu đăng nhập Xiaohongshu lên máy chủ ✓" : "Máy chủ báo lỗi " + code;
                } catch (Exception e) {
                    msg = "Không gửi được cookie: " + e.getMessage();
                }
                final String fm = msg;
                runOnUiThread(new Runnable() {
                    public void run() {
                        Toast.makeText(MainActivity.this, fm, Toast.LENGTH_LONG).show();
                        start();
                    }
                });
            }
        }).start();
    }

    private void handleIntent(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return;
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        if (text == null) return;
        Matcher m = Pattern.compile("https?://[^\\s，,。]+").matcher(text);
        pendingLink = m.find() ? m.group() : text.trim();
        Toast.makeText(this, "Đã nhận link video", Toast.LENGTH_SHORT).show();
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    private static String normalize(String url) {
        String u = url == null ? "" : url.trim();
        Matcher m = Pattern.compile("https?://[^\\s]+").matcher(u);
        if (m.find()) u = m.group();
        else if (!u.isEmpty() && !u.startsWith("http")) u = "https://" + u;
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    // ---------------------------------------------------------------- WebView
    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            String srv = server();
            if (url.startsWith("file:///android_asset/") || (!srv.isEmpty() && url.startsWith(srv))) {
                return false;
            }
            if (loginMode && (isXhs(url) || url.startsWith("https://"))) {
                if (url.startsWith("xhsdiscover:") || url.startsWith("intent:")) return true;  // không mở app ngoài
                return false;
            }
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception ignored) {
            }
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (req.isForMainFrame() && !loginMode) {
                showSetup("Không kết nối được máy chủ. Kiểm tra Colab còn chạy không, rồi dán link mới.");
            }
        }

        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest req, WebResourceResponse resp) {
            if (req.isForMainFrame() && !loginMode && resp.getStatusCode() >= 500) {
                int code = resp.getStatusCode();
                if (server().contains(".hf.space")) {
                    showSetup("Máy chủ Hugging Face đang khởi động (lỗi " + code
                            + "). Chờ 1–2 phút rồi bấm \"Thử lại\".");
                } else {
                    // Cloudflare 1033 / 530: đường hầm Colab đã đóng -> link hết hạn
                    showSetup("Link máy chủ đã hết hạn (lỗi " + code
                            + "). Trên Colab chạy ô \"Lấy link mới\" rồi dán link vào đây.");
                }
            }
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            super.onPageStarted(view, url, favicon);
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = cb;
            try {
                Intent i = params.createIntent();
                i.addCategory(Intent.CATEGORY_OPENABLE);
                startActivityForResult(Intent.createChooser(i, "Chọn file"), REQ_FILE);
            } catch (Exception e) {
                fileCallback = null;
                Toast.makeText(MainActivity.this, "Không mở được trình chọn file", Toast.LENGTH_SHORT).show();
                return false;
            }
            return true;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    /** Lưu video / phụ đề về máy: video vào thư mục Phim (Movies/VideoViet), file khác vào Tải xuống. */
    private class Downloader implements DownloadListener {
        @Override
        public void onDownloadStart(String url, String ua, String disposition, String mime, long length) {
            try {
                String name = URLUtil.guessFileName(url, disposition, mime);
                boolean isVideo = (mime != null && mime.startsWith("video")) || name.endsWith(".mp4");
                DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
                r.setMimeType(isVideo ? "video/mp4" : mime);
                r.addRequestHeader("User-Agent", ua);
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) r.addRequestHeader("Cookie", cookie);
                r.setTitle(name);
                r.setDescription("Video Tiếng Việt");
                r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                r.setDestinationInExternalPublicDir(
                        isVideo ? Environment.DIRECTORY_MOVIES : Environment.DIRECTORY_DOWNLOADS, "VideoViet/" + name);
                r.allowScanningByMediaScanner();
                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                dm.enqueue(r);
                Toast.makeText(MainActivity.this,
                        isVideo ? "Đang lưu video vào thư mục Phim/VideoViet…" : "Đang tải " + name,
                        Toast.LENGTH_LONG).show();
            } catch (Exception e) {
                Toast.makeText(MainActivity.this, "Lỗi tải file: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        }
    }

    // ---------------------------------------------------------------- cầu nối JS <-> Android
    private class Bridge {
        @JavascriptInterface
        public void saveServer(final String url) {
            final String u = normalize(url);
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, u).apply();
            runOnUiThread(new Runnable() {
                public void run() {
                    web.clearHistory();
                    start();
                }
            });
        }

        @JavascriptInterface
        public void loginXhs() {
            runOnUiThread(new Runnable() {
                public void run() {
                    startXhsLogin();
                }
            });
        }

        @JavascriptInterface
        public String getServer() {
            return server();
        }

        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(new Runnable() {
                public void run() {
                    showSetup(null);
                }
            });
        }

        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Video Tiếng Việt", text));
            runOnUiThread(new Runnable() {
                public void run() {
                    Toast.makeText(MainActivity.this, "Đã chép", Toast.LENGTH_SHORT).show();
                }
            });
        }

        @JavascriptInterface
        public String paste() {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm.hasPrimaryClip() && cm.getPrimaryClip().getItemCount() > 0) {
                CharSequence t = cm.getPrimaryClip().getItemAt(0).coerceToText(MainActivity.this);
                return t == null ? "" : t.toString();
            }
            return "";
        }

        @JavascriptInterface
        public void reload() {
            runOnUiThread(new Runnable() {
                public void run() {
                    start();
                }
            });
        }

        @JavascriptInterface
        public String version() {
            return "1.0";
        }
    }
}
