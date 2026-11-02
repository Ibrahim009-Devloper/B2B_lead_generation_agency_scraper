# Project Overview & Core Philosophy: Python-First, AI-Supervised Lead Generation System

## 1. Golden Rule (মূল নীতি)
1. **"Python does the heavy lifting; AI only supervises, verifies, and summarizes."**
2. **NO AI Scraping:** কখনোই পুরো ওয়েবসাইট বা কাঁচা HTML খোঁজার জন্য AI ব্যবহার করা যাবে না। ওয়েবসাইট ক্রলিং, পেজ ভিজিট, ইমেইল এক্সট্রাকশন এবং টেকনিক্যাল ভেরিফিকেশন ১০০% **Python** করবে।
3. **AI as Supervisor & Verifier Only:** শুধুমাত্র যেসব ওয়েবসাইটে পাইথন কমপক্ষে ১টি ভ্যালিড ইমেইল এবং টার্গেট বিজনেসের প্রাথমিক লক্ষণ পাবে, কেবল সেই সাইটের বাছাইকৃত টেক্সট ও ইমেইল AI-এর কাছে যাবে। AI ফাইনাল ভেরিফাই করবে ব্যবসাটি আসলেই আমাদের সার্ভিস কিনবে কি না এবং ব্যবসার গভীর সামারি ও পার্সোনালাইজড ইমেইল গাইড তৈরি করবে।
4. **Daily Target:** প্রতিদিন ২৫০টি ইউনিক, ভেরিফায়েড এবং হাই-কোয়ালিটি বিটুবি (B2B) ইমেইল সংগ্রহ করা।
5. **Exclude Unnecessary Data:** কোনো ফোন নাম্বার, সোশ্যাল মিডিয়া লিংক বা লিংকডইন প্রোফাইল খোঁজার পেছনে সময় বা রিসোর্স নষ্ট করা যাবে না। শুধুমাত্র ভেরিফায়েড ইমেইল এবং বিজনেস ইন্টেলিজেন্সের ওপর ফোকাস থাকবে।

---

## 2. Step-by-Step Practical Pipeline (পাইথন ও এআই-এর কাজের ধাপ)

### Phase 1: Multi-Source Discovery & Strict Deduplication (100% Python)
একটি নির্দিষ্ট ডিরেক্টরির ওপর নির্ভর করা সম্পূর্ণ নিষিদ্ধ। প্রতিদিন ২৫০টি ভেরিফায়েড ইমেইল পেতে হলে পাইথনকে ঘুরিয়ে-ফিরিয়ে (Round-Robin পদ্ধতিতে) একাধিক সোর্স থেকে নতুন কোম্পানির ডোমেইন আনতে হবে।
* **Multiple Sources:** শুধুমাত্র Clutch বা GoodFirms নয়; DesignRush, Sortlist, UpCity, YellowPages, ই-কমার্স স্টোর ফুটপ্রিন্ট এবং সার্চ ইঞ্জিন (DuckDuckGo/Brave HTML) থেকে নিশ অনুযায়ী সরাসরি কোম্পানির ওয়েবসাইট খুঁজে আনতে হবে।
* **Directory & Junk Blacklist:** কোনো ডিরেক্টরি সাইট, ব্লগ সাইট, নিউজ পোর্টাল, সোশ্যাল মিডিয়া বা "Top 10 Agencies" জাতীয় আর্টিকেল লিংক শুরুতেই পাইথন ফিল্টার করে বাদ দেবে।
* **Lifetime Deduplication (SQLite Database):** 
  * স্ক্র্যাপ করার আগেই ডাটাবেসে চেক করতে হবে এই **Domain** আগে কখনো চেক করা হয়েছে কি না। হয়ে থাকলে সাথে সাথে বাদ।
  * ইমেইল পাওয়ার পর চেক করতে হবে এই **Email Address** আগে কখনো ডাটাবেসে ঢুকেছে কি না। একই ডোমেইন বা একই ইমেইল জীবনে দ্বিতীয়বার লিস্টে আসবে না।

### Phase 2: Targeted Multi-Page Scraping (100% Python)
ডোমেইনটি নতুন হলে পাইথন (`curl_cffi` ও `BeautifulSoup` ব্যবহার করে) ওই ওয়েবসাইটে ঢুকবে এবং শুধুমাত্র নিচের নির্দিষ্ট পেজগুলো খুঁজে বের করে স্ক্র্যাপ করবে:
* **Target Pages (5-6 Pages Max):** 
  1. Homepage (`/`)
  2. Contact Page (`/contact`, `/contact-us`, `/get-in-touch`)
  3. About Page (`/about`, `/about-us`, `/who-we-are`, `/company`)
  4. Team / Leadership Page (`/team`, `/our-team`, `/leadership`, `/management`)
  5. Services / Solutions Page (`/services`, `/solutions`, `/what-we-do`)
* **Critical Rule on HTML Cleaning:** টোকেন বাঁচানোর নামে কখনোই ওয়েবসাইটের **Header** বা **Footer** ডিলিট করা যাবে না। কারণ ৯০% কোম্পানির আসল ইমেইল এবং সংক্ষিপ্ত পরিচয় ফুটারে থাকে। শুধুমাত্র স্ক্রিপ্ট, স্টাইল (CSS), ছবি এবং অপ্রয়োজনীয় কোড বাদ দিয়ে পরিষ্কার টেক্সটটুকু নিতে হবে।

### Phase 3: Email Extraction, Priority & Technical Verification (100% Python)
এই ধাপে কোনো AI ব্যবহার করা হবে না। পাইথন নিজে ইমেইল বের করবে এবং ভেরিফাই করবে:
* **DNS MX Record Check:** ডোমেইনটিতে আদৌ মেইল আদান-প্রদান সচল আছে কি না তা পাইথন ডোমেইন নেম সার্ভার (MX Record) দিয়ে চেক করবে। মেইল সার্ভার না থাকলে সাইটটি সাথে সাথে বাদ যাবে।
* **Junk Email Filtering:** ছবির নাম বা সিস্টেম ইমেইল (যেমন: `.png`, `.jpg`, `noreply@`, `privacy@`, `sentry@`, `example@`, `wix@`) পাইথন রেগুলার এক্সপ্রেশন দিয়ে নিজেই বাদ দেবে।
* **Zero-Email Drop Rule (0 Token Cost):** পুরো ৫-৬টি পেজ খুঁজেও যদি কোনো ভ্যালিড ইমেইল না পাওয়া যায়, তবে পাইথন ওই ওয়েবসাইটটি তখনই বাদ দিয়ে ডাটাবেসে ব্লক করে রাখবে। **ইমেইল না পেলে AI কল করা সম্পূর্ণ নিষিদ্ধ।**
* **Email Priority Logic:**
  * **Priority 1 (Owner / Decision Maker):** যদি সাইট বা টিম পেজ থেকে মালিক, ফাউন্ডার বা কোনো ব্যক্তির নামের ইমেইল পাওয়া যায় (যেমন: `john@`, `ceo@`, `founder@`), তবে সেটিকে প্রধান ইমেইল হিসেবে নিতে হবে।
  * **Priority 2 (Generic Business Email):** মালিকের ইমেইল না পাওয়া গেলে কোম্পানির ভ্যালিড জেনেরিক ইমেইল (যেমন: `info@`, `hello@`, `contact@`, `sales@`) প্রধান ইমেইল হিসেবে গ্রহণ করতে হবে।
  * **Backup Emails:** একই সাইটে একাধিক ভ্যালিড ইমেইল পাওয়া গেলে সেরা ১টিকে Primary Email এবং বাকি ১-২টিকে Backup Email কলামে রাখতে হবে।

### Phase 4: 2-Layer Target Business Verification (টার্গেট ক্লায়েন্ট ভেরিফায়ার)
ওয়েবসাইটে ইমেইল থাকলেই সেটি আমাদের লিড নয় (যেমন: রেস্তোরাঁ, সেলুন বা সরকারি সাইট আমাদের সার্ভিস কিনবে না)। তাই ব্যবসাটি সত্যিই আমাদের টার্গেট ক্লায়েন্ট কি না তা নিশ্চিত করতে ২-স্তরের কড়া ভেরিফিকেশন চলবে:

#### Layer 1: Python Pre-Verifier (Hard Keyword Filter - 0 Token Cost)
AI-এর কাছে পাঠানোর আগেই পাইথন স্ক্র্যাপ করা টেক্সট পরীক্ষা করে প্রাথমিক আবর্জনা পরিষ্কার করবে:
* **Negative Keyword Block:** সাইটের লেখায় যদি Non-profit, Charity, Government, .gov, .edu, Restaurant Menu, Salon, Hospital, News Portal, Casino, Wikipedia বা এ জাতীয় অপ্রাসঙ্গিক ক্যাটাগরি থাকে, পাইথন সাথে সাথে সাইটটি বাদ দেবে।
* **Dead/Parked Site Drop:** সাইটে যদি পর্যাপ্ত কন্টেন্ট না থাকে বা "Domain for Sale" / "Under Construction" লেখা থাকে, তবে তা বাদ যাবে।
* **Positive Industry Signals:** পাইথন নিশ্চিত করবে সাইটটিতে আমাদের টার্গেট ইন্ডাস্ট্রির কোনো লক্ষণ আছে কি না:
  * **B2B / Marketing / Lead Gen Agency:** (Outbound, Lead Generation, B2B Marketing, SEO Agency, Cold Email, Sales Pipeline, Digital Agency, Growth).
  * **E-commerce / Wholesale Brand:** (Shopify, WooCommerce, Catalog, Wholesale, Distributor, Brand, E-commerce).
  * **Data-Heavy Firms (Real Estate / Recruiting / SaaS):** (Property Listings, Staffing, Recruitment, Market Research, Analytics, SaaS).

#### Layer 2: AI Business Verifier (The Real Judge)
পাইথন প্রি-ফিল্টার পাস করার পর AI ভেরিফায়ার এজেন্ট ওই ৫-৬টি পেজের লেখা পড়ে ৪টি কঠিন শর্ত মিলিয়ে ফাইনাল ভেরিফিকেশন করবে:
1. **Real Business vs. Content/Directory Check:** এটি কি সত্যিকারের কোনো ব্যবসা যারা প্রোডাক্ট বা সার্ভিস বিক্রি করে, নাকি এটি কেবল একটি ব্লগ, নিউজ সাইট বা ডিরেক্টরি লিস্ট? (ব্লগ বা ডিরেক্টরি হলে সাথে সাথে REJECTED)।
2. **Service Buying Need Verification (আমাদের সার্ভিস কি এদের সত্যিই লাগবে?):**
   * **Marketing/Lead Gen/SEO Agency হলে:** এদের ক্লায়েন্টদের জন্য প্রতিনিয়ত ফ্রেশ লিড এবং কাস্টম ডাটা স্ক্র্যাপিং লাগে। (Verified = YES)
   * **E-commerce/Retail/Wholesale হলে:** এদের কম্পিটিটরদের প্রাইস মনিটরিং এবং বিটুবি ডিলার লিড ডাটা লাগে। (Verified = YES)
   * **Recruitment/Real Estate/SaaS হলে:** এদের ক্যান্ডিডেট, প্রপার্টি লিস্টিং বা মার্কেট ডাটা অটোমেশন লাগে। (Verified = YES)
   * **অপ্রাসঙ্গিক ব্যবসা (যেমন: লোকাল প্লাম্বার, সেলুন বা খুচরা দোকান) হলে:** এরা কখনোই স্ক্র্যাপিং বা অটোমেশন সার্ভিস কিনবে না। (Verified = NO / REJECTED)
3. **Company Size Sweet Spot Check:** এদের About এবং Team পেজ পড়ে AI দেখবে এটি মাঝারি বা ছোট আকারের অ্যাক্টিভ কোম্পানি (২ থেকে ৫০ জন কর্মী) কি না, যেখানে ডিসিশন-মেকারদের কাছে সরাসরি কোল্ড ইমেইলে পৌঁছানো সম্ভব। বিশাল মাল্টিন্যাশনাল বা এন্টারপ্রাইজ কোম্পানি হলে বাদ দেবে।
4. **Email-to-Business Matching:** পাইথন যে ইমেইলটি তুলে এনেছে, AI নিশ্চিত করবে সেটি আসলেই ওই কোম্পানির নিজস্ব ইমেইল কি না (অন্য কোনো থার্ড-পার্টি বা বিজ্ঞাপনের ইমেইল ভুল করে চলে এসেছে কি না)।

**Strict Gatekeeper Rule:** উপরের ৪টি শর্তে ১০০% পাস করলেই কেবল AI লিডটিকে `VERIFIED_TARGET` হিসেবে সিলমোহর দেবে এবং পরবর্তী ধাপে (সামারি ও ইমেইল ড্রাফটিং) নিয়ে যাবে।

### Phase 5: Deep Business Summary & Personalization Guide (AI Supervisor)
শুধুমাত্র `VERIFIED_TARGET` হিসেবে উত্তীর্ণ কোম্পানিগুলোর জন্য AI নিচের তথ্যগুলো তৈরি করবে:
* **Owner & Role Identification:**
  * স্ক্র্যাপ করা `/about` ও `/team` পেজের লেখা পড়ে কোম্পানির ওনার, ফাউন্ডার বা প্রধান ব্যক্তির নাম ও পদবি (যদি টেক্সটে উল্লেখ থাকে) বের করবে।
* **Deep Business Dossier (ব্যবসার খুঁটিনাটি সামারি):**
  * **তারা কী কাজ করে (Core Business):** কোম্পানিটি মূলত কী সার্ভিস বা প্রোডাক্ট বিক্রি করে এবং তাদের বিজনেস মডেল কী।
  * **তাদের ক্লায়েন্ট কারা (Target Audience):** এরা কাদের কাছে সার্ভিস বিক্রি করে (যেমন: রিয়েল এস্টেট, ডেন্টিস্ট, ই-কমার্স ব্র্যান্ড, সাস স্টার্টআপ ইত্যাদি)।
  * **আমাদের সার্ভিস কেন তাদের দরকার (Service Need / Pain Point):** তাদের ব্যবসার কোন জায়গায় আমাদের স্ক্র্যাপিং, প্রাইস মনিটরিং বা বিটুবি লিড ডাটা কাজে লাগবে।
* **Personalization Hook & Cold Email Draft (কীভাবে মেইল করলে রিপ্লাই আসবে):**
  * **Human Personalization Guide:** একজন মানুষ যখন তাদের মেইল করবে, তখন ওয়েবসাইটের ঠিক কোন নির্দিষ্ট পয়েন্টটি (যেমন: তাদের বিশেষ কোনো সার্ভিস, কোনো কেস স্টাডি, তাদের নির্দিষ্ট কোনো ক্লায়েন্ট নিশ বা শহরের নাম) উল্লেখ করলে মনে হবে আমরা ওয়েবসাইটটি খুঁটিয়ে পড়েছি—তার একটি স্পষ্ট নির্দেশনা বা গাইডলাইন লেখা থাকবে।
  * **Ready-to-Send Personalized Email:** ৭৫ শব্দের নিচে, কোনো লিংক বা স্প্যামি শব্দ ছাড়া একদম প্রাকৃতিক ও পার্সোনালাইজড একটি রেডিমেড কোল্ড ইমেইল ড্রাফট তৈরি করবে, যেখানে তাদের কাজের প্রশংসা করে ফ্রি স্যাম্পল ডাটা বা সলিউশন দেওয়ার অফার থাকবে।

---

## 3. Final Output Format (Excel / Database 12 Columns)
আউটপুট শিটে শুধুমাত্র ১০০% ভেরিফায়েড লিডগুলো যাবে। প্রতিদিন ২৫০টি ভেরিফায়েড লিডের জন্য নিচের ১২টি পরিষ্কার কলাম সংরক্ষিত হবে:

1. **Company Name** (কোম্পানির সঠিক নাম)
2. **Website Domain** (ডোমেইন লিংক)
3. **Verification Status** (`VERIFIED_TARGET` + কোন ক্যাটাগরির ক্লায়েন্ট)
4. **Primary Verified Email** (মালিকের ইমেইল, অথবা সেরা বিজনেস ইমেইল)
5. **Email Category** (`Owner/Personal` নাকি `Generic Business`)
6. **Backup Emails** (ওই সাইটে পাওয়া অতিরিক্ত ১-২টি ভ্যালিড ইমেইল)
7. **Decision Maker Name & Role** (ওয়েবসাইটে পাওয়া গেলে নাম ও পদবি)
8. **Complete Business Summary** (খুঁটিনাটি বিবরণ) (তারা কী করে, কীভাবে আয় করে এবং তাদের মূল সার্ভিস কী)
9. **Their Target Clients** (তাদের কাস্টমার কারা)
10. **How to Pitch / Personalization Guide** (মানুষের পড়ার জন্য নোট: এই কোম্পানিকে ঠিক কী বলে মেইল করলে পার্সোনালাইজড মনে হবে এবং কেন তারা আমাদের সার্ভিস কিনবে)
11. **Ready Personalized Cold Email** (সরাসরি পাঠানোর উপযোগী কাস্টমাইজড ইমেইল)
12. **Source Footprint** (কোন সোর্স বা ডিরেক্টরি থেকে লিডটি পাওয়া গেছে)
