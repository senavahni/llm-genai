"""Set kesetaraan embedding (LGW-V1-01): 100 teks Indonesia/Inggris — 30 pendek ID, 30 pendek EN,
20 campur (code-switching), 20 panjang (±1.000 token). Dipakai scripts/spike_embed.py dan
tests/hardware/test_embed.py. Deterministik (tanpa random) agar angka spike bisa diulang."""

# instruksi query sesuai model card Qwen3-Embedding (dokumen tanpa prefix)
QUERY_TASK = "Given a web search query, retrieve relevant passages that answer the query"
QUERY_PREFIX = f"Instruct: {QUERY_TASK}\nQuery: "

SHORT_ID = [
    "Penjualan kopi kemasan naik 12% pada kuartal ketiga.",
    "Siapa pesaing utama kami di pasar minuman siap saji Jawa Barat?",
    "Harga bahan baku gula diperkirakan stabil hingga akhir tahun.",
    "Kampanye media sosial bulan lalu menjangkau dua juta pengguna.",
    "Distributor di Surabaya meminta tambahan stok untuk musim liburan.",
    "Bagaimana tren belanja daring generasi Z di Indonesia?",
    "Perusahaan logistik itu membuka gudang baru di Cikarang.",
    "Margin kotor produk premium lebih tinggi dibanding produk reguler.",
    "Konsumen mengeluhkan kemasan yang sulit dibuka.",
    "Tim penjualan menargetkan 50 mitra ritel baru tahun depan.",
    "Regulasi label halal berlaku untuk semua produk makanan olahan.",
    "Pangsa pasar merek lokal meningkat di kota tingkat dua.",
    "Ulasan pelanggan di marketplace rata-rata bintang empat koma lima.",
    "Biaya iklan per klik naik menjelang Hari Belanja Nasional.",
    "Pabrik di Karawang beroperasi tiga shift sejak Oktober.",
    "Apa saja kanal distribusi paling efektif untuk produk kecantikan?",
    "Survei menunjukkan 60% responden memilih pembayaran dompet digital.",
    "Ekspor kerajinan rotan ke Eropa tumbuh dua digit.",
    "Laporan keuangan tahunan dirilis akhir Maret.",
    "Program loyalitas meningkatkan pembelian ulang sebesar delapan persen.",
    "Startup agritech itu mendapat pendanaan seri B.",
    "Musim hujan memengaruhi pengiriman ke wilayah timur.",
    "Kemitraan dengan warung tradisional memperluas jangkauan produk.",
    "Data penjualan per provinsi tersedia di dasbor pemasaran.",
    "Pesaing meluncurkan varian rasa baru dengan harga lebih murah.",
    "Inflasi pangan bulan September tercatat 2,1 persen.",
    "Bagaimana cara menghitung nilai umur pelanggan?",
    "Agensi kreatif menyiapkan tiga konsep iklan televisi.",
    "Permintaan produk organik meningkat di kalangan keluarga muda.",
    "Rapat evaluasi kampanye dijadwalkan hari Kamis pukul sepuluh.",
]

SHORT_EN = [
    "Quarterly revenue grew 8% year over year.",
    "Who are the leading suppliers of recycled packaging in Southeast Asia?",
    "The new pricing strategy targets price-sensitive urban shoppers.",
    "Customer churn dropped after the onboarding redesign.",
    "Our competitor opened three flagship stores in Jakarta.",
    "What is the average order value on the mobile app?",
    "Shipping delays were caused by port congestion.",
    "The brand refresh improved recall among young adults.",
    "Retail partners requested more point-of-sale materials.",
    "Influencer campaigns outperformed paid search last month.",
    "The market for plant-based snacks is expected to double by 2030.",
    "Inventory turnover improved in the second half.",
    "How should we segment B2B customers by purchasing behavior?",
    "The company announced a strategic partnership with a regional bank.",
    "Net promoter score rose to 52 after the service upgrade.",
    "Raw material costs remain the largest risk to margins.",
    "The product launch event drew over five hundred attendees.",
    "Email open rates are highest on Tuesday mornings.",
    "Which channels drive the most qualified leads?",
    "The warehouse automation project is on schedule.",
    "Consumer confidence improved slightly in October.",
    "A competitor filed a patent for biodegradable bottle caps.",
    "Sales reps spend too much time on manual reporting.",
    "The loyalty app now supports QR code payments.",
    "Market research shows strong demand for ready-to-drink tea.",
    "Our distribution network covers 34 provinces.",
    "What are the key drivers of brand switching?",
    "The board approved the expansion budget for next year.",
    "Social listening detected a spike in negative mentions.",
    "Seasonal demand peaks during the Ramadan period.",
]

MIXED = [
    "Tolong buat summary dari meeting kemarin tentang go-to-market strategy.",
    "Conversion rate di landing page baru naik setelah kita ganti call-to-action.",
    "Budget untuk paid ads Q4 perlu di-review sebelum approval.",
    "Customer journey kita masih bocor di tahap checkout.",
    "Apakah ada insight dari dashboard tentang repeat order?",
    "Tim sales butuh pitch deck yang lebih compelling untuk enterprise client.",
    "KPI utama tahun ini adalah market share dan customer retention.",
    "Kompetitor sedang agresif dengan flash sale dan free shipping.",
    "Lead scoring model perlu di-update dengan data CRM terbaru.",
    "Brand awareness di Sumatra masih rendah dibanding Jawa.",
    "Please translate this product description ke Bahasa Indonesia yang natural.",
    "A/B test untuk subject line email menunjukkan hasil signifikan.",
    "Supply chain disruption bikin lead time jadi dua kali lipat.",
    "Kita perlu benchmark pricing terhadap tiga kompetitor terdekat.",
    "Engagement rate konten video lebih tinggi daripada carousel.",
    "Onboarding flow untuk merchant baru terlalu panjang.",
    "Forecast demand bulan depan pakai data historis tiga tahun.",
    "Customer feedback soal after-sales service cukup negatif.",
    "Partnership dengan e-commerce platform bisa boost visibility.",
    "Retention cohort Januari lebih baik dibanding Desember.",
]

_LONG_ID_PARAS = [
    "Industri makanan dan minuman di Indonesia terus menunjukkan pertumbuhan yang stabil dalam "
    "beberapa tahun terakhir, didorong oleh bertambahnya kelas menengah, urbanisasi, dan "
    "perubahan gaya hidup konsumen yang semakin menginginkan produk praktis dan siap saji.",
    "Perusahaan yang ingin bersaing perlu memahami perilaku konsumen secara mendalam, mulai dari "
    "preferensi rasa, sensitivitas harga, hingga kanal pembelian yang paling sering digunakan, "
    "baik ritel modern, warung tradisional, maupun platform belanja daring.",
    "Strategi distribusi menjadi kunci, terutama di negara kepulauan dengan infrastruktur yang "
    "belum merata. Biaya logistik ke wilayah timur dapat mencapai dua hingga tiga kali lipat "
    "dibandingkan pengiriman di Pulau Jawa, sehingga perencanaan stok harus cermat.",
    "Di sisi pemasaran, kombinasi kampanye digital dan aktivasi di lapangan terbukti efektif. "
    "Konten video pendek, kolaborasi dengan kreator lokal, dan promosi di titik penjualan "
    "saling melengkapi untuk membangun kesadaran merek sekaligus mendorong pembelian.",
    "Data penjualan harian dari mitra ritel memungkinkan tim analitik mendeteksi perubahan "
    "permintaan lebih cepat. Dengan model peramalan yang baik, perusahaan dapat mengurangi "
    "kelebihan stok, menekan biaya penyimpanan, dan menghindari kehabisan barang.",
    "Regulasi juga perlu diperhatikan, termasuk kewajiban sertifikasi halal, aturan label gizi, "
    "dan ketentuan iklan untuk produk tertentu. Kepatuhan sejak awal mencegah penarikan produk "
    "yang merugikan reputasi dan keuangan perusahaan.",
]

_LONG_EN_PARAS = [
    "Market intelligence combines structured data such as sales figures, pricing, and inventory "
    "levels with unstructured signals from news articles, social media, product reviews, and "
    "competitor websites to produce a coherent picture of the competitive landscape.",
    "A robust pipeline begins with reliable collection: crawling public pages on a schedule, "
    "deduplicating near-identical documents, and tagging each record with its source, language, "
    "and retrieval time so that analysts can judge freshness and credibility.",
    "Once collected, documents are split into chunks, embedded into a vector space, and indexed "
    "for semantic search. Retrieval quality depends heavily on chunk size, overlap, and whether "
    "queries are encoded with task-specific instructions.",
    "Analysts then ask questions in natural language, such as which competitors changed prices "
    "this month or which product categories receive the most complaints, and the system returns "
    "the most relevant passages together with citations.",
    "Cost control matters at scale. Running embeddings locally on an integrated GPU avoids "
    "per-token charges for bulk ingestion, while remote models remain available for complex "
    "reasoning tasks where their higher quality justifies the price.",
    "Finally, governance ensures that personal data is excluded, that access is limited by "
    "project, and that every model call is logged with tags for job, stage, and agent so that "
    "costs and quality can be audited later.",
]

LONG_TARGET_CHARS = 4800  # ±1.000 token Qwen untuk teks ID/EN


def _long_text(paras: list[str], offset: int) -> str:
    out: list[str] = []
    i = offset
    while sum(len(p) + 1 for p in out) < LONG_TARGET_CHARS:
        out.append(paras[i % len(paras)])
        i += 1
    return " ".join(out)


def _long_texts() -> list[str]:
    texts = []
    for k in range(20):
        if k % 4 == 3:  # campuran: paragraf ID dan EN bergantian
            mixed = [p for pair in zip(_LONG_ID_PARAS, _LONG_EN_PARAS, strict=True) for p in pair]
            texts.append(_long_text(mixed, k))
        else:
            texts.append(_long_text(_LONG_ID_PARAS if k % 2 == 0 else _LONG_EN_PARAS, k))
    return texts


def eval_set() -> list[tuple[str, str]]:
    """[(kategori, teks)] — 100 item."""
    items = (
        [("short_id", t) for t in SHORT_ID]
        + [("short_en", t) for t in SHORT_EN]
        + [("mixed", t) for t in MIXED]
        + [("long", t) for t in _long_texts()]
    )
    assert len(items) == 100
    return items


def query_set() -> list[str]:
    """Teks yang juga diuji sebagai query (dengan QUERY_PREFIX): 10 ID + 10 EN pendek."""
    return SHORT_ID[:10] + SHORT_EN[:10]
