# Python-First, AI-Supervised Lead Generation System
**System Architecture & Operating Rules (Version 3.1 - Master Aligned)**
**Target ICP:** B2B Agencies & Buyers of Custom Web Scraping & Data Pipeline Services
**Core Philosophy:** Python does the heavy lifting; AI only supervises, verifies, and summarizes.

---

## 1. Golden Rule (মূল নীতি)
1. **"Python does the heavy lifting; AI only supervises, verifies, and summarizes."**
2. **NO AI Scraping:** কখনোই পুরো ওয়েবসাইট বা কাঁচা HTML খোঁজার জন্য AI ব্যবহার করা যাবে না। ওয়েবসাইট ক্রলিং, পেজ ভিজিট, ইমেইল এক্সট্রাকশন এবং টেকনিক্যাল ভেরিফিকেশন ১০০% **Python** করবে।
3. **AI as Supervisor & Verifier Only:** শুধুমাত্র যেসব ওয়েবসাইটে পাইথন কমপক্ষে ১টি ভ্যালিড ইমেইল এবং টার্গেট বিজনেসের প্রাথমিক লক্ষণ পাবে, কেবল সেই সাইটের বাছাইকৃত টেক্সট ও ইমেইল AI-এর কাছে যাবে। AI ফাইনাল ভেরিফাই করবে ব্যবসাটি আসলেই আমাদের সার্ভিস কিনবে কি না এবং ব্যবসার গভীর সামারি ও পার্সোনালাইজড ইমেইল গাইড তৈরি করবে।
4. **Daily Target:** প্রতিদিন ২৫০টি ইউনিক, ভেরিফায়েড এবং হাই-কোয়ালিটি বিটুবি (B2B) ইমেইল সংগ্রহ করা।
5. **Exclude Unnecessary Data:** কোনো ফোন নাম্বার, সোশ্যাল মিডিয়া লিংক বা লিঙ্কডইন প্রোফাইল খোঁজার পেছনে সময় বা রিসোর্স নষ্ট করা যাবে না। শুধুমাত্র ভেরিফায়েড ইমেইল এবং বিজনেস ইন্টেলিজেন্সের ওপর ফোকাস থাকবে।

---

## 2. Step-by-Step Practical Pipeline

### Phase 1: Multi-Source Discovery & Strict Deduplication (100% Python)
* **Round-Robin Multi-Source:** শুধুমাত্র Clutch নয়; GoodFirms, DesignRush, UpCity, Sortlist, YellowPages, ই-কমার্স ফুটপ্রিন্ট এবং সার্চ ইঞ্জিন (DuckDuckGo/Brave HTML) থেকে নিশ অনুযায়ী সরাসরি কোম্পানির ওয়েবসাইট খুঁজে আনতে হবে।
* **Directory & Junk Blacklist:** ডিরেক্টরি সাইট, ব্লগ, নিউজ পোর্টাল বা "Top 10 Agencies" জাতীয় আর্টিকেল লিংক শুরুতেই পাইথন ফিল্টার করে বাদ দেবে।
* **Lifetime Deduplication (SQLite Database):**
  * **Domain Deduplication:** স্ক্র্যাপ করার আগেই ডাটাবেসে চেক করতে হবে এই ডোমেইন আগে কখনো চেক করা হয়েছে কি না। হয়ে থাকলে সাথে সাথে বাদ।
  * **Email Deduplication:** ইমেইল পাওয়ার পর চেক করতে হবে এই ইমেইল অ্যাড্রেস আগে কখনো ডাটাবেসে ঢুকেছে কি না। একই ডোমেইন বা একই ইমেইল জীবনে দ্বিতীয়বার লিস্টে আসবে না।

### Phase 2: Targeted Multi-Page Scraping (100% Python)
ডোমেইনটি নতুন হলে পাইথন (`curl_cffi` ও `BeautifulSoup` ব্যবহার করে) ওই ওয়েবসাইটে ঢুকবে এবং শুধুমাত্র ৫-৬টি নির্দিষ্ট পেজ স্ক্র্যাপ করবে:
1. **Homepage** (`/`)
2. **Contact Page** (`/contact`, `/contact-us`, `/get-in-touch`)
3. **About Page** (`/about`, `/about-us`, `/who-we-are`, `/company`)
4. **Team / Leadership Page** (`/team`, `/our-team`, `/leadership`, `/management`)
5. **Services / Solutions Page** (`/services`, `/solutions`, `/what-we-do`)

* **Critical Rule on HTML Cleaning:** টোকেন বাঁচানোর নামে কখনোই ওয়েবসাইটের **Header** বা **Footer** ডিলিট করা যাবে না। কারণ ৯০% কোম্পানির আসল ইমেইল এবং সংক্ষিপ্ত পরিচয় ফুটারে থাকে। শুধুমাত্র স্ক্রিপ্ট (`<script>`), স্টাইল (`<style>`), ছবি (`<img>`), এবং এসভিজি (`<svg>`) বাদ দিয়ে পরিষ্কার টেক্সটটুকু নিতে হবে।

### Phase 3: Email Extraction, Priority & Technical Verification (100% Python)
* **DNS MX Record Check:** পাইথন সরাসরি ডোমেইনের DNS MX রেকর্ড চেক করে নিশ্চিত করবে মেইল সার্ভার সচল কি না (`LIKELY_VALID` / `VERIFIED`)। মেইল সার্ভার না থাকলে সাইটটি সাথে সাথে বাদ যাবে।
* **Junk Email Filtering:** সিস্টেম ও ডামি ইমেইল (`.png`, `.jpg`, `noreply@`, `privacy@`, `sentry@`, `example@`, `wix@`) পাইথন রেজেক্স দিয়ে বাদ দেবে।
* **Zero-Email Drop Rule (0 Token Cost):** পুরো ৫-৬টি পেজ খুঁজেও যদি কোনো ভ্যালিড ইমেইল না পাওয়া যায়, তবে পাইথন ওই ওয়েবসাইটটি তখনই বাদ দিয়ে ডাটাবেসে ব্লক করে রাখবে। **ইমেইল না পেলে AI কল করা সম্পূর্ণ নিষিদ্ধ।**
* **Email Priority Logic:**
  * **Priority 1 (Owner / Decision Maker):** মালিক, ফাউন্ডার বা ব্যক্তির নামের ইমেইল (`john@`, `ceo@`, `founder@`) পেলে সেটি Primary Email।
  * **Priority 2 (Generic Business Email):** মালিকের ইমেইল না পাওয়া গেলে কোম্পানির ভ্যালিড জেনেরিক ইমেইল (`info@`, `hello@`, `contact@`, `sales@`) Primary Email।
  * **Backup Emails:** একাধিক ভ্যালিড ইমেইল পাওয়া গেলে সেরা ১টিকে Primary Email এবং অতিরিক্ত ১-২টিকে Backup Email হিসেবে রাখতে হবে।

### Phase 4: 2-Layer Target Business Verification (টার্গেট ক্লায়েন্ট ভেরিফায়ার)

#### Layer 1: Python Pre-Verifier (Hard Keyword Filter - 0 Token Cost)
* **Negative Keyword Block:** Non-profit, Charity, Government, .gov, .edu, Restaurant Menu, Salon, Hospital, News Portal, Casino, Wikipedia ইত্যাদি থাকলে সাথে সাথে বাদ।
* **Dead/Parked Site Drop:** "Domain for Sale" / "Under Construction" বা <১২০ ক্যারেক্টার টেক্সট থাকলে বাদ।
* **Positive Industry Signals:** B2B/Marketing Agency, E-commerce/Wholesale Brand, অথবা Data-Heavy Firm (Real Estate/Recruiting/SaaS)-এর লক্ষণ থাকতে হবে।

#### Layer 2: AI Business Verifier (The Real Judge)
AI ৪টি কঠিন শর্ত মিলিয়ে ফাইনাল ভেরিফিকেশন করবে:
1. **Real Business vs. Content/Directory Check:** সত্যিকারের ব্যবসা কি না (ব্লগ বা ডিরেক্টরি হলে REJECTED)।
2. **Service Buying Need Verification:** স্ক্র্যাপিং বা বিটুবি লিড ডেটা প্রয়োজন কি না (YES অথবা REJECTED)।
3. **Company Size Sweet Spot Check:** অ্যাক্টিভ ছোট-মাঝারি কোম্পানি (২ থেকে ৫০ জন কর্মী) কি না।
4. **Email-to-Business Matching:** সংগৃহীত ইমেইল ওই কোম্পানির নিজস্ব কি না।
* **Strict Gatekeeper:** ৪টি শর্তে ১০০% পাস করলেই কেবল `VERIFIED_TARGET (<Category>)` সিলমোহর পাবে।

### Phase 5: Deep Business Summary & Personalization Guide (AI Supervisor)
* **Owner & Role Identification:** ওনার/ফাউন্ডারের নাম ও পদবি বের করবে।
* **Deep Business Dossier:**
  * **Core Business:** তারা মূলত কী সার্ভিস বা প্রোডাক্ট বিক্রি করে।
  * **Target Audience:** কাদের কাছে বিক্রি করে (রিয়েল এস্টেট, ডেন্টিস্ট, ই-কমার্স ইত্যাদি)।
  * **Service Need / Pain Point:** তাদের কেন স্ক্র্যাপিং বা লিড ডেটা দরকার।
* **Personalization Hook & Cold Email Draft:**
  * **Human Personalization Guide:** সেলস রেপের জন্য স্পেসিফিক পিচ গাইডলাইন।
  * **Ready-to-Send Personalized Email:** ৭৫ শব্দের নিচে, কোনো লিংক ছাড়া, ফ্রি স্যাম্পল অফারসহ প্রস্তুত ড্রাফট।

---

## 3. Targeted Lead Qualification & Sweet Spot Scoring
- **Targeted Company & Service Fit (Max 30 pts):**
  - Tier 1 (B2B Lead Gen, Cold Email, Sales Prospecting, Appointment Setting): 28-30 pts.
  - Tier 2 (SEO & Local SEO, B2B Data Research, Recruiting, B2B Marketing): 20-25 pts.
  - Non-ICP: 0 pts (Rejected).
- **Lead Need Signals & Data Dependency (Max 20 pts):**
  - Outbound campaigns, lead lists, directory scraping, map audits, or list building needs.
- **Company Size Sweet Spot (Max 15 pts):**
  - **2-10 employees:** 15 pts (Highest value! Boutique, agile agency, owner-operated).
  - **10-50 employees:** 12 pts (Medium-high value).
  - **50-200 employees:** 8 pts (Moderate value, accepted).
  - **200+ employees:** 5 pts (Enterprise, accepted).
- **Buying Intent (Max 20 pts):**
  - Active outbound campaigns creating continuous demand for fresh prospect datasets.
- **Decision-Maker (Max 10 pts):**
  - Verified Founder, Owner, or CEO name found on site. (LinkedIn is 100% optional — zero penalty).
- **Deliverable Email (Max 5 pts):**
  - Deliverable verified email via DNS MX check: 5 pts. (Phone is 100% optional — zero penalty).

---

## 4. Final Output Format (Excel / Database 12 Columns)
আউটপুট টেবিলে নির্ধারিত ১২টি কলাম:
1. `Company Name`
2. `Website Domain`
3. `Verification Status` (`VERIFIED_TARGET` + ক্যাটাগরি)
4. `Primary Verified Email`
5. `Email Category` (`Owner/Personal` নাকি `Generic Business`)
6. `Backup Emails` (অতিরিক্ত ১-২টি ভ্যালিড ইমেইল)
7. `Decision Maker Name & Role` (ওয়েবসাইটে পাওয়া গেলে নাম ও পদবি)
8. `Complete Business Summary` (কী কাজ করে, কীভাবে আয় করে, মূল সার্ভিস)
9. `Their Target Clients` (তাদের কাস্টমার কারা)
10. `How to Pitch / Personalization Guide` (মানুষের পড়ার জন্য স্পেসিফিক আউটরিচ গাইড)
11. `Ready Personalized Cold Email` (সরাসরি পাঠানোর উপযোগী ইমেইল ড্রাফট, <৭৫ শব্দ)
12. `Source Footprint` (কোন ডিরেক্টরি বা সার্চ সোর্স থেকে পাওয়া গেছে)
