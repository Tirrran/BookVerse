const STORAGE_KEY = "bookverse_local_books_v2";
const TOKEN_REGEX = /[A-Za-zА-Яа-яЁё0-9-]+/g;
const NAME_REGEX = /\b[А-ЯЁ][а-яё]{2,}\b/g;
const CHAPTER_WORD_REGEX = /\b(?:глава|главе|главы|главу|главой|главам|главах|chapter)\b/i;
const CHAPTER_HEADING_REGEX = /^(?:\s*)(?:глава|chapter)\s+([^\n]+)$/gim;
const CHAPTER_FILLER_WORDS = new Set(["в", "во", "на", "по", "из", "к", "о", "об", "про"]);
const CHUNK_CACHE = new Map();

const STOPWORDS = new Set([
    "и", "в", "во", "на", "по", "а", "но", "как", "что", "кто", "где", "когда", "зачем",
    "почему", "это", "этот", "эта", "эти", "для", "из", "от", "до", "за", "под", "при",
    "ли", "же", "бы", "был", "была", "были", "быть", "или", "не", "ни", "мы", "вы", "он",
    "она", "они", "его", "ее", "её", "их", "нас", "вас", "так", "тут", "там", "уже",
]);

const THEME_MARKERS = ["вера", "бог", "душ", "совест", "смир", "грех", "добро", "зло", "иде", "тем"];
const REL_MARKERS = ["отнош", "друж", "люб", "враж", "конфликт", "между"];
const ACTION_MARKERS = ["дела", "сдела", "пош", "приш", "сказ", "увид", "встрет", "реш", "узнал", "взя"];
const CAUSAL_MARKERS = ["потому", "так как", "поэтому", "из-за", "чтобы", "для того"];

const CHAPTER_WORD_HINTS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
    "одиннадцат": 11,
    "двенадцат": 12,
    "тринадцат": 13,
    "четырнадцат": 14,
    "пятнадцат": 15,
    "шестнадцат": 16,
    "семнадцат": 17,
    "восемнадцат": 18,
    "девятнадцат": 19,
    "двадцат": 20,
    "тридцат": 30,
    "сорок": 40,
    "пятидесят": 50,
    "шестидесят": 60,
    "семидесят": 70,
    "восьмидесят": 80,
    "девяност": 90,
};

function safeJsonParse(raw, fallback) {
    try {
        const parsed = JSON.parse(raw);
        return parsed ?? fallback;
    } catch (_error) {
        return fallback;
    }
}

function loadRawBooks() {
    return safeJsonParse(localStorage.getItem(STORAGE_KEY), []);
}

function saveRawBooks(books) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(books));
    CHUNK_CACHE.clear();
}

function stripExtension(filename = "") {
    return filename.replace(/\.[^.]+$/, "").trim() || filename || "Без названия";
}

function normalizeStoredBook(raw) {
    return {
        id: String(raw.id),
        filename: raw.filename || raw.original_filename || "book.txt",
        title: raw.title || stripExtension(raw.filename || raw.original_filename || ""),
        file_type: (raw.file_type || "TXT").toUpperCase(),
        upload_date: raw.upload_date || new Date().toISOString(),
        progress: Number.isFinite(raw.progress) ? Math.max(0, Math.min(100, raw.progress)) : 0,
        content: typeof raw.content === "string" ? raw.content : "",
    };
}

function encodeBookList(books) {
    return books.map((book) => ({
        id: String(book.id),
        filename: book.filename,
        title: book.title,
        file_type: book.file_type,
        upload_date: book.upload_date,
        progress: book.progress,
        content: book.content,
    }));
}

export function getBooks() {
    return loadRawBooks().map(normalizeStoredBook);
}

export function getBookById(bookId) {
    const id = String(bookId);
    return getBooks().find((book) => book.id === id) || null;
}

export function getBookMetas() {
    return getBooks()
        .map((book) => ({
            id: book.id,
            filename: book.filename,
            title: book.title,
            file_type: book.file_type,
            upload_date: book.upload_date,
            progress: book.progress,
            cover_url: null,
            author: null,
        }))
        .sort((a, b) => new Date(b.upload_date).getTime() - new Date(a.upload_date).getTime());
}

export function deleteBookById(bookId) {
    const id = String(bookId);
    const books = getBooks();
    const filtered = books.filter((book) => book.id !== id);
    saveRawBooks(encodeBookList(filtered));
}

export function updateBookProgress(bookId, progressPercent) {
    const id = String(bookId);
    const clamped = Math.max(0, Math.min(100, Number(progressPercent) || 0));
    const books = getBooks();
    const updated = books.map((book) => (
        book.id === id
            ? { ...book, progress: clamped }
            : book
    ));
    saveRawBooks(encodeBookList(updated));
}

export function getLibraryStats() {
    const books = getBooks();
    const booksRead = books.filter((book) => (book.progress || 0) >= 100).length;
    const booksInProgress = books.filter((book) => (book.progress || 0) > 0 && (book.progress || 0) < 100).length;
    return {
        books_read: booksRead,
        books_in_progress: booksInProgress,
        total: books.length,
    };
}

function countReplacementChars(text) {
    let count = 0;
    for (const ch of text) {
        if (ch === "\ufffd") count += 1;
    }
    return count;
}

function decodeTextBuffer(buffer) {
    const utf8 = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
    const utf8BadRatio = countReplacementChars(utf8) / Math.max(1, utf8.length);
    if (utf8BadRatio < 0.01) {
        return utf8;
    }
    try {
        const cp1251 = new TextDecoder("windows-1251", { fatal: false }).decode(buffer);
        return cp1251;
    } catch (_error) {
        return utf8;
    }
}

function sanitizeText(text) {
    return (text || "")
        .replace(/\r\n/g, "\n")
        .replace(/\u0000/g, "")
        .trim();
}

function extractTextFromFb2Xml(xmlText) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlText, "application/xml");
    if (doc.getElementsByTagName("parsererror").length > 0) {
        return xmlText.replace(/<[^>]+>/g, " ");
    }

    const bodies = Array.from(doc.getElementsByTagName("body"));
    const chunks = [];
    for (const body of bodies) {
        const sections = Array.from(body.getElementsByTagName("section"));
        if (!sections.length) {
            const bodyText = body.textContent || "";
            if (bodyText.trim()) chunks.push(bodyText.trim());
            continue;
        }
        for (const section of sections) {
            const titleNode = section.getElementsByTagName("title")[0];
            const titleText = titleNode ? (titleNode.textContent || "").trim() : "";
            if (titleText) {
                chunks.push(`Глава ${titleText}`);
            }
            const paragraphs = Array.from(section.getElementsByTagName("p"))
                .map((node) => (node.textContent || "").trim())
                .filter(Boolean);
            if (paragraphs.length) {
                chunks.push(paragraphs.join("\n\n"));
            }
        }
    }
    return chunks.join("\n\n");
}

async function readBookContent(file) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    const buffer = await file.arrayBuffer();
    const decoded = decodeTextBuffer(buffer);

    if (ext === "fb2") {
        return sanitizeText(extractTextFromFb2Xml(decoded));
    }
    if (ext === "txt") {
        return sanitizeText(decoded);
    }
    throw new Error("Поддерживаются только .txt и .fb2");
}

export async function addBookFromFile(file) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!["txt", "fb2"].includes(ext)) {
        throw new Error("Поддерживаются только .txt и .fb2");
    }

    const content = await readBookContent(file);
    if (!content.trim()) {
        throw new Error("Файл пустой или не содержит текста");
    }

    const books = getBooks();
    const id = `b_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const book = normalizeStoredBook({
        id,
        filename: file.name,
        title: stripExtension(file.name),
        file_type: ext.toUpperCase(),
        upload_date: new Date().toISOString(),
        progress: 0,
        content,
    });
    books.push(book);
    saveRawBooks(encodeBookList(books));
    return book;
}

function normalizeToken(token) {
    const normalized = token.toLowerCase().replace(/ё/g, "е");
    if (/^\d+$/.test(normalized)) return normalized;
    if (normalized.length <= 3) return normalized;

    const suffixes = [
        "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ее", "ие", "ые", "ое",
        "ий", "ый", "ой", "ем", "им", "ым", "ом", "их", "ых", "ую", "ая", "яя",
        "ах", "ях", "ам", "ям", "ов", "ев", "а", "я", "ы", "и", "е", "у", "ю", "о",
    ];
    for (const suffix of suffixes) {
        if (normalized.endsWith(suffix) && normalized.length - suffix.length >= 3) {
            return normalized.slice(0, -suffix.length);
        }
    }
    return normalized;
}

function tokenize(text) {
    return Array.from((text || "").matchAll(TOKEN_REGEX), (match) => match[0]);
}

function tokenizeTerms(text) {
    return tokenize(text)
        .map((token) => normalizeToken(token))
        .filter((token) => token && !STOPWORDS.has(token));
}

function romanToInt(value) {
    const roman = (value || "").toLowerCase().trim();
    if (!roman) return null;
    const map = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };
    let total = 0;
    let prev = 0;
    for (let i = roman.length - 1; i >= 0; i -= 1) {
        const current = map[roman[i]];
        if (!current) return null;
        if (current < prev) total -= current;
        else {
            total += current;
            prev = current;
        }
    }
    return total > 0 ? total : null;
}

function parseChapterToken(token) {
    const value = (token || "").toLowerCase().replace(/ё/g, "е").trim();
    if (!value) return null;
    const numMatch = value.match(/^(\d+)(?:\s*[-–—]?\s*[a-zа-я]+)?$/);
    if (numMatch) {
        const number = Number(numMatch[1]);
        return number > 0 ? number : null;
    }
    const roman = romanToInt(value);
    if (roman) return roman;
    for (const [stem, number] of Object.entries(CHAPTER_WORD_HINTS)) {
        if (value.startsWith(stem)) return number;
    }
    return null;
}

function parseChapterPhrase(phrase) {
    const raw = (phrase || "")
        .toLowerCase()
        .replace(/ё/g, "е")
        .replace(/[№#]/g, " ")
        .replace(/[\"'«»()[\],.?!:;]/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    if (!raw) return null;

    const numberMatch = raw.match(/^(\d+)(?:\s*[-–—]?\s*[a-zа-я]+)?$/);
    if (numberMatch) {
        const number = Number(numberMatch[1]);
        return number > 0 ? number : null;
    }

    const roman = romanToInt(raw.replace(/\s+/g, ""));
    if (roman) return roman;

    let parts = raw.split(" ").map((item) => item.trim()).filter(Boolean);
    while (parts.length && CHAPTER_FILLER_WORDS.has(parts[0])) {
        parts = parts.slice(1);
    }
    if (!parts.length) return null;
    if (parts.length === 1) return parseChapterToken(parts[0]);

    const first = parseChapterToken(parts[0]) || 0;
    const second = parseChapterToken(parts[1]) || 0;
    if (first >= 20 && first % 10 === 0 && second >= 1 && second <= 9) {
        return first + second;
    }

    const parsed = parts.map(parseChapterToken).filter((item) => Number.isFinite(item));
    return parsed.length === 1 ? parsed[0] : null;
}

function extractRequestedChapter(query) {
    const normalized = (query || "").toLowerCase().replace(/ё/g, "е");
    const patterns = [
        /(?:глава|главе|главы|главу|главой|chapter)\s*(?:№\s*)?([ivxlcdm]+|\d+(?:\s*[-–—]?\s*[a-zа-я]+)?|[a-zа-яё-]+(?:\s+[a-zа-яё-]+){0,2})/gi,
        /([ivxlcdm]+|\d+(?:\s*[-–—]?\s*[a-zа-я]+)?|[a-zа-яё-]+(?:\s+[a-zа-яё-]+){0,2})\s*(?:глава|главе|главы|главу|главой|chapter)/gi,
    ];
    for (const pattern of patterns) {
        for (const match of normalized.matchAll(pattern)) {
            const parsed = parseChapterPhrase(match[1]);
            if (parsed) return parsed;
        }
    }
    return null;
}

function hasChapterKeyword(query) {
    return CHAPTER_WORD_REGEX.test((query || "").toLowerCase().replace(/ё/g, "е"));
}

function lineForOffset(text, offset) {
    if (offset <= 0) return 1;
    return text.slice(0, Math.min(offset, text.length)).split("\n").length;
}

function buildChapterSpans(text) {
    const matches = Array.from(text.matchAll(CHAPTER_HEADING_REGEX));
    if (!matches.length) return [];
    return matches.map((match, idx) => {
        const token = (match[1] || "").split(/\s+/).slice(0, 3).join(" ");
        const number = parseChapterPhrase(token) || (idx + 1);
        const start = match.index || 0;
        const end = idx + 1 < matches.length ? (matches[idx + 1].index || text.length) : text.length;
        return {
            number,
            title: match[0].trim(),
            start,
            end,
        };
    });
}

function chapterForOffset(spans, offset) {
    if (!spans.length) return null;
    for (const span of spans) {
        if (span.start <= offset && offset < span.end) {
            return span;
        }
    }
    if (offset < spans[0].start) return spans[0];
    return spans[spans.length - 1];
}

function splitTextChunks(book) {
    const cacheKey = `${book.id}:${book.content.length}`;
    const cached = CHUNK_CACHE.get(cacheKey);
    if (cached) return cached;

    const text = book.content || "";
    const spans = buildChapterSpans(text);
    const paragraphs = text.split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
    const chunks = [];
    let cursor = 0;
    let bufferText = "";
    let chunkStart = 0;

    const pushChunk = (chunkText, start, end) => {
        const cleaned = chunkText.trim();
        if (!cleaned) return;
        const span = chapterForOffset(spans, start);
        const chapter = span ? span.number : null;
        chunks.push({
            text: cleaned,
            start,
            end,
            chapter_number: chapter,
            chapter_title: span ? span.title : null,
            line_start: lineForOffset(text, start),
            line_end: lineForOffset(text, end),
            terms: tokenizeTerms(cleaned),
        });
    };

    for (const paragraph of paragraphs) {
        const at = text.indexOf(paragraph, cursor);
        if (at < 0) continue;
        const paraStart = at;
        const paraEnd = at + paragraph.length;
        cursor = paraEnd;

        if (!bufferText) {
            bufferText = paragraph;
            chunkStart = paraStart;
        } else if (bufferText.length + paragraph.length + 2 <= 1200) {
            bufferText += `\n\n${paragraph}`;
        } else {
            pushChunk(bufferText, chunkStart, paraStart);
            bufferText = paragraph;
            chunkStart = paraStart;
        }
    }

    if (bufferText) {
        pushChunk(bufferText, chunkStart, text.length);
    }

    if (!spans.length && chunks.length) {
        const virtualCount = Math.min(10, Math.max(3, Math.floor(chunks.length / 25) + 1));
        for (let i = 0; i < chunks.length; i += 1) {
            chunks[i].chapter_number = Math.floor(i * virtualCount / Math.max(1, chunks.length)) + 1;
            chunks[i].chapter_title = `Часть ${chunks[i].chapter_number}`;
        }
    }

    CHUNK_CACHE.set(cacheKey, chunks);
    return chunks;
}

function lexicalOverlap(queryTerms, chunkTerms) {
    const querySet = new Set(queryTerms);
    const chunkSet = new Set(chunkTerms);
    let hits = 0;
    for (const term of querySet) {
        if (chunkSet.has(term)) hits += 1;
    }
    return {
        hits,
        ratio: hits / Math.max(1, querySet.size),
    };
}

function formatAvailableChapters(chapters) {
    if (!chapters.length) return "";
    if (chapters.length <= 12) return chapters.join(", ");
    return `${chapters.slice(0, 5).join(", ")}, ..., ${chapters.slice(-3).join(", ")}`;
}

function chapterRequestErrorMessage(chapterNumber, availableChapters) {
    const hint = formatAvailableChapters(availableChapters);
    if (chapterNumber == null) {
        const base = "Не удалось определить номер главы. Укажите номер, например: «что было во 2-й главе».";
        return hint ? `${base} Доступные главы: ${hint}.` : base;
    }
    return hint
        ? `Глава ${chapterNumber} не найдена. Доступные главы: ${hint}.`
        : `Глава ${chapterNumber} не найдена.`;
}

function collectAvailableChapters(books) {
    const chapters = new Set();
    for (const book of books) {
        for (const chunk of splitTextChunks(book)) {
            if (Number.isFinite(chunk.chapter_number)) chapters.add(chunk.chapter_number);
        }
    }
    return Array.from(chapters).sort((a, b) => a - b);
}

function toFragment(book, chunk, score) {
    return {
        book_id: book.id,
        book_title: book.filename,
        fragment: chunk.text,
        score: Number(score.toFixed(4)),
        location: {
            chapter: chunk.chapter_number || null,
            chapter_title: chunk.chapter_title || null,
            line_start: chunk.line_start,
            line_end: chunk.line_end,
            char_start: chunk.start,
            char_end: chunk.end,
        },
    };
}

function selectBooksByIds(bookIds = []) {
    const all = getBooks();
    if (!Array.isArray(bookIds) || !bookIds.length) return all;
    const allowed = new Set(bookIds.map((id) => String(id)));
    return all.filter((book) => allowed.has(String(book.id)));
}

export function searchBooksLocal(query, options = {}) {
    const topK = Math.max(1, Number(options.top_k || options.topK || 5));
    const books = selectBooksByIds(options.book_ids || options.bookIds || []);
    if (!books.length) {
        return { found: false, message: "Нет загруженных книг для поиска", fragments: [] };
    }

    const chapterNumber = extractRequestedChapter(query);
    const chapterKeyword = hasChapterKeyword(query);
    const availableChapters = collectAvailableChapters(books);
    if (chapterKeyword && chapterNumber == null) {
        return { found: false, message: chapterRequestErrorMessage(null, availableChapters), fragments: [] };
    }
    if (chapterNumber != null && !availableChapters.includes(chapterNumber)) {
        return { found: false, message: chapterRequestErrorMessage(chapterNumber, availableChapters), fragments: [] };
    }

    const queryTerms = tokenizeTerms(query);
    if (!queryTerms.length && chapterNumber == null) {
        return { found: false, message: "Введите более конкретный запрос", fragments: [] };
    }

    const scored = [];
    for (const book of books) {
        const chunks = splitTextChunks(book);
        for (const chunk of chunks) {
            if (chapterNumber != null && chunk.chapter_number !== chapterNumber) continue;
            const overlap = lexicalOverlap(queryTerms, chunk.terms);

            let score = 0;
            if (chapterNumber != null) {
                score += 0.5;
                score += overlap.hits * 0.18;
            } else {
                if (overlap.hits === 0) continue;
                score += overlap.ratio;
                score += overlap.hits * 0.05;
            }
            score += Math.min(0.15, chunk.text.length / 2400);
            if (score < 0.2) continue;
            scored.push(toFragment(book, chunk, score));
        }
    }

    if (!scored.length) {
        return { found: false, message: "Подходящие фрагменты не найдены", fragments: [] };
    }

    scored.sort((a, b) => b.score - a.score);
    const selected = [];
    const seen = new Set();
    for (const fragment of scored) {
        const key = `${fragment.book_id}:${fragment.location.chapter}:${fragment.location.line_start}`;
        if (seen.has(key)) continue;
        seen.add(key);
        selected.push(fragment);
        if (selected.length >= topK) break;
    }
    return { found: true, message: null, fragments: selected };
}

function splitSentences(text) {
    return (text || "")
        .split(/(?<=[.!?])\s+|\n+/)
        .map((line) => line.trim())
        .filter((line) => line.length >= 20 && /\p{L}/u.test(line));
}

function detectIntent(question) {
    const q = (question || "").toLowerCase().replace(/ё/g, "е");
    if (hasChapterKeyword(q)) return "chapter";
    if (/как\s+зовут|как\s+звали|имя\b|фамили/.test(q)) return "name_lookup";
    if (/описание героя|опиши героя|характер героя|какой герой|характеристика героя/.test(q)) return "character_description";
    if (/зачем|почему|по какой причине|для чего/.test(q)) return "motivation";
    if (/отношени|взаимоотнош|между персонаж|между героя/.test(q)) return "relationships";
    if (/основная тема|главная тема|смысл|идея книги|тема книги/.test(q)) return "theme";
    if (/что делал|что делает|какие поступки|чем заним/.test(q)) return "actions";
    if (/по итогу|чем заканч|финал|концовк|в конце/.test(q)) return "finale";
    if (/в начале/.test(q)) return "beginning";
    if (/в середине/.test(q)) return "middle";
    if (/ключевые события|главные события|важные события/.test(q)) return "events";
    return "plot";
}

function pickSentencesByMarkers(fragments, markers, limit = 2) {
    const scored = [];
    for (const fragment of fragments) {
        for (const sentence of splitSentences(fragment.fragment)) {
            const lowered = sentence.toLowerCase().replace(/ё/g, "е");
            const hits = markers.reduce((sum, marker) => sum + (lowered.includes(marker) ? 1 : 0), 0);
            if (hits > 0) {
                scored.push({ sentence, score: hits + fragment.score * 0.2, chapter: fragment.location?.chapter || 0 });
            }
        }
    }
    scored.sort((a, b) => b.score - a.score);
    const selected = [];
    const seen = new Set();
    for (const row of scored) {
        const key = row.sentence.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        selected.push(row.sentence);
        if (selected.length >= limit) break;
    }
    return selected;
}

function extractNameCandidates(text) {
    const blacklist = new Set([
        "Глава", "Россия", "Бог", "Господь", "Потому", "Однако", "Теперь", "Тогда",
    ]);
    const names = [];
    for (const match of text.matchAll(NAME_REGEX)) {
        const value = match[0];
        if (!blacklist.has(value)) names.push(value);
    }
    return names;
}

function buildAnswer(question, intent, fragments) {
    const allSentences = [];
    for (const fragment of fragments) {
        for (const sentence of splitSentences(fragment.fragment)) {
            allSentences.push({ sentence, chapter: fragment.location?.chapter || null });
        }
    }
    if (!allSentences.length) return "";

    if (intent === "chapter") {
        const chapter = fragments[0]?.location?.chapter;
        const intro = chapter ? `По главе ${chapter}:` : "По этой главе:";
        return `${intro} ${allSentences.slice(0, 2).map((row) => row.sentence).join(" ")}`.trim();
    }

    if (intent === "name_lookup") {
        const names = [];
        for (const fragment of fragments) {
            const lowered = fragment.fragment.toLowerCase().replace(/ё/g, "е");
            if (!/зовут|звали|имя|по имени/.test(lowered)) continue;
            names.push(...extractNameCandidates(fragment.fragment));
        }
        if (names.length) {
            return `По найденным фрагментам: ${names[0]}.`;
        }
        return "В найденных фрагментах нет прямого указания имени.";
    }

    if (intent === "character_description") {
        const selected = pickSentencesByMarkers(fragments, ["характер", "внешн", "человек", "сильн", "добр", "строг"], 2);
        if (selected.length) {
            return `По тексту образ героя описан так: ${selected.join(" ")}`;
        }
        return "В найденных фрагментах нет явного описания героя.";
    }

    if (intent === "actions") {
        const selected = pickSentencesByMarkers(fragments, ACTION_MARKERS, 2);
        const body = selected.length ? selected : allSentences.slice(0, 2).map((row) => row.sentence);
        return `По тексту действия героя описаны так: ${body.join(" ")}`;
    }

    if (intent === "motivation") {
        const selected = pickSentencesByMarkers(fragments, CAUSAL_MARKERS, 2);
        const body = selected.length ? selected : allSentences.slice(0, 2).map((row) => row.sentence);
        return `По тексту причины действий героя выглядят так: ${body.join(" ")}`;
    }

    if (intent === "relationships") {
        const selected = pickSentencesByMarkers(fragments, REL_MARKERS, 2);
        const body = selected.length ? selected : allSentences.slice(0, 2).map((row) => row.sentence);
        return `По этим фрагментам отношения между персонажами показаны так: ${body.join(" ")}`;
    }

    if (intent === "theme") {
        const selected = pickSentencesByMarkers(fragments, THEME_MARKERS, 2);
        const body = selected.length ? selected : allSentences.slice(0, 2).map((row) => row.sentence);
        return `Основная тема по найденным фрагментам: ${body.join(" ")}`;
    }

    if (intent === "finale") {
        const sentence = allSentences[allSentences.length - 1]?.sentence || allSentences[0].sentence;
        return `По итогу: ${sentence}`;
    }

    if (intent === "beginning") {
        return `В начале книги: ${allSentences[0].sentence}`;
    }

    if (intent === "middle") {
        return `В середине книги: ${allSentences[Math.floor(allSentences.length / 2)].sentence}`;
    }

    if (intent === "events") {
        const parts = allSentences.slice(0, 3).map((row, idx) => `${idx + 1}) ${row.sentence}`);
        return `Ключевые события по книге: ${parts.join(" ")}`;
    }

    const first = allSentences[0]?.sentence || "";
    const middle = allSentences[Math.floor(allSentences.length / 2)]?.sentence || "";
    const last = allSentences[allSentences.length - 1]?.sentence || "";
    return `В начале: ${first} Далее: ${middle || first} К финалу: ${last || middle || first}`.trim();
}

export function askBooksLocal(question, options = {}) {
    const topK = Math.max(1, Number(options.top_k || options.topK || 5));
    const citationsK = Math.max(1, Number(options.citations_k || options.citationsK || 3));
    const search = searchBooksLocal(question, {
        top_k: topK,
        book_ids: options.book_ids || options.bookIds || [],
    });

    if (!search.found) {
        return {
            found: false,
            answer: search.message || "К сожалению, ответ не найден в загруженных книгах.",
            citations: [],
        };
    }

    const intent = detectIntent(question);
    const citations = search.fragments.slice(0, citationsK);
    const answer = buildAnswer(question, intent, citations.length ? citations : search.fragments);
    return {
        found: Boolean(answer),
        answer: answer || "К сожалению, ответ не найден в загруженных книгах.",
        citations,
    };
}

