# Shivanshu Cafe Website

All Online Services Available Here – Gaya, Bihar

## Files
```
index.html      → Main website (all 6 pages)
manifest.json   → PWA manifest
sw.js           → Service Worker (offline support)
icon-192.png    → App icon
icon-512.png    → App icon (large)
render.yaml     → Render deployment config
```

---

## 🚀 Render Par Deploy Karne Ka Tarika

### Step 1 – GitHub Repository Banao
1. [github.com](https://github.com) par jaao
2. **New Repository** click karo
3. Name: `shivanshu-cafe` rakho
4. **Public** select karo
5. **Create repository** click karo

### Step 2 – Files Upload Karo
GitHub repository mein jaake:
1. **uploading an existing file** click karo
2. Ye saari files drag & drop karo:
   - `index.html`
   - `manifest.json`
   - `sw.js`
   - `icon-192.png`
   - `icon-512.png`
   - `render.yaml`
3. **Commit changes** click karo

### Step 3 – Render Par Deploy Karo
1. [render.com](https://render.com) par jaao
2. **Sign up** karo (GitHub se login kar sakte ho)
3. Dashboard mein **New +** → **Static Site** click karo
4. **Connect a repository** mein apna `shivanshu-cafe` repo select karo
5. Ye settings rakho:
   - **Name:** `shivanshu-cafe`
   - **Branch:** `main`
   - **Publish directory:** `.` (dot)
   - Build Command: khali chhod do
6. **Create Static Site** click karo

### Step 4 – Live!
- Kuch seconds mein website live ho jaayegi
- Render ek free URL dega jaise: `https://shivanshu-cafe.onrender.com`
- Baad mein custom domain `shivanshucafe.in` bhi add kar sakte ho

---

## 🌐 Custom Domain Add Karna (Optional)
1. Render Dashboard → apni site → **Settings** → **Custom Domains**
2. `shivanshucafe.in` type karo → **Add**
3. Apne domain provider (GoDaddy/BigRock etc.) mein DNS settings mein:
   - **CNAME record** add karo:
     - Name: `www`
     - Value: `shivanshu-cafe.onrender.com`
   - **A record** add karo:
     - Name: `@`
     - Value: Render ka IP (Render dashboard mein milega)

---

## 📱 PWA (App Install)
Website HTTPS par deploy hone ke baad mobile Chrome mein **"App Install Karein"** button automatically aayega.
