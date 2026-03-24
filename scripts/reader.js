const rawHost = window.location.hostname || '127.0.0.1';
const API_HOST =
    rawHost === '0.0.0.0' || rawHost === '[::]' ? '127.0.0.1' : rawHost;
const API_BASE_CANDIDATES = Array.from(
    new Set([
        `http://${API_HOST}:8000`,
        'http://127.0.0.1:8000',
        'http://localhost:8000',
    ]),
);

// Базовый лимит слов на страницу; дальше корректируется под экран и размер шрифта.
const WORDS_PER_PAGE_BASE = 420;
const WORDS_PER_PAGE_MIN = 220;
const WORDS_PER_PAGE_MAX = 1200;
const MAX_STRICT_SEARCH_MATCHES = 1500;

let apiBaseCache = null;
let bookText = '';
let totalPages = 0;
let currentPage = 1;
let pages = [];
let chapters = [];
let chapterHintTimer = null;
let activeSearchResult = null;
let pageTextCache = [];
let pageSearchTextCache = [];
let readerSearchHits = [];
let readerSearchIndex = -1;
let readerSearchQuery = '';
let readerSearchWholeWord = false;
let readerSearchTruncated = false;
let readerSearchHitPages = [];
let readerSearchHitPageToIndex = new Map();

function getAuthToken() {
    const existing = localStorage.getItem('authToken');
    if (existing) return existing;

    const fallback = 'auth-disabled';
    localStorage.setItem('authToken', fallback);
    return fallback;
}

async function apiFetch(path, options = {}) {
    const candidates = apiBaseCache
        ? [apiBaseCache, ...API_BASE_CANDIDATES.filter((item) => item !== apiBaseCache)]
        : API_BASE_CANDIDATES;

    let lastError = null;
    for (const base of candidates) {
        try {
            const response = await fetch(`${base}${path}`, options);
            apiBaseCache = base;
            return response;
        } catch (error) {
            lastError = error;
        }
    }

    throw lastError || new Error('Не удалось подключиться к API');
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function normalizeErrorMessage(source, fallback = 'Ошибка') {
    if (!source) return fallback;

    if (source instanceof Error) {
        return normalizeErrorMessage(source.message, fallback);
    }

    if (typeof source === 'string') {
        const text = source.trim();
        return text || fallback;
    }

    if (Array.isArray(source)) {
        const messages = source
            .map((item) => normalizeErrorMessage(item, ''))
            .filter(Boolean);
        return messages.length ? messages.join('; ') : fallback;
    }

    if (typeof source === 'object') {
        if (typeof source.detail === 'string' && source.detail.trim()) {
            return source.detail.trim();
        }
        if (Array.isArray(source.detail) && source.detail.length) {
            return normalizeErrorMessage(source.detail, fallback);
        }
        if (typeof source.message === 'string' && source.message.trim()) {
            return source.message.trim();
        }
        if (typeof source.msg === 'string' && source.msg.trim()) {
            const location = Array.isArray(source.loc)
                ? source.loc.filter(Boolean).join('.')
                : '';
            return location ? `${location}: ${source.msg.trim()}` : source.msg.trim();
        }
    }

    return fallback;
}

function countWords(text) {
    const tokens = String(text || '')
        .trim()
        .split(/\s+/)
        .filter(Boolean);
    return tokens.length;
}

function normalizeBookText(text) {
    return String(text || '')
        .replace(/\uFEFF/g, '')
        .replace(/\r\n?/g, '\n')
        .replace(/\t/g, ' ')
        .replace(/[ \f\v]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function getWordsPerPage() {
    const viewportWidth = window.innerWidth || 1366;
    const viewportHeight = window.innerHeight || 900;
    const savedFontSize = parseInt(localStorage.getItem('fontSize') || '16', 10);
    const fontSize = Number.isFinite(savedFontSize) ? savedFontSize : 16;

    // Шире/выше экран -> больше слов; крупный шрифт -> меньше слов.
    // Формула усилена, чтобы на больших экранах страница заполнялась плотнее.
    const widthFactor = clamp(viewportWidth / 1366, 0.55, 1.9);
    const heightFactor = clamp(viewportHeight / 768, 0.8, 1.6);
    const fontFactor = clamp(16 / fontSize, 0.7, 1.15);

    const adaptive = Math.round(
        WORDS_PER_PAGE_BASE * widthFactor * heightFactor * fontFactor * 0.9,
    );
    return clamp(adaptive, WORDS_PER_PAGE_MIN, WORDS_PER_PAGE_MAX);
}

function splitIntoParagraphs(text) {
    const normalized = normalizeBookText(text);
    if (!normalized) return [];

    const paragraphs = [];
    let index = 0;
    let line = 1;

    while (index < normalized.length) {
        while (index < normalized.length && normalized[index] === '\n') {
            index += 1;
            line += 1;
        }
        if (index >= normalized.length) break;

        const blockStart = index;
        const blockStartLine = line;

        while (index < normalized.length) {
            if (normalized[index] === '\n' && normalized[index + 1] === '\n') {
                break;
            }
            if (normalized[index] === '\n') {
                line += 1;
            }
            index += 1;
        }

        const blockEnd = index;
        const rawBlock = normalized.slice(blockStart, blockEnd);
        const cleaned = rawBlock
            .replace(/[ \t]*\n[ \t]*/g, ' ')
            .replace(/\s{2,}/g, ' ')
            .trim();

        if (cleaned) {
            paragraphs.push({
                text: cleaned,
                charStart: blockStart,
                charEnd: blockEnd,
                lineStart: blockStartLine,
                lineEnd: line,
            });
        }
    }

    if (paragraphs.length <= 2) {
        const lineParagraphs = [];
        const lines = normalized.split('\n');
        let cursor = 0;

        lines.forEach((rawLine, lineIndex) => {
            const cleanedLine = rawLine.trim();
            const lineStart = lineIndex + 1;
            const lineEnd = lineStart;
            const charStart = cursor;
            const charEnd = cursor + rawLine.length;

            if (cleanedLine) {
                lineParagraphs.push({
                    text: cleanedLine,
                    charStart,
                    charEnd,
                    lineStart,
                    lineEnd,
                });
            }
            cursor += rawLine.length + 1;
        });

        if (lineParagraphs.length > paragraphs.length) {
            return lineParagraphs;
        }
    }

    return paragraphs;
}

function splitLongParagraph(text, maxWords) {
    const normalized = String(text || '')
        .replace(/\s+/g, ' ')
        .trim();
    if (!normalized) return [];

    if (countWords(normalized) <= maxWords) {
        return [normalized];
    }

    const sentenceParts = normalized.match(/[^.!?…]+(?:[.!?…]+|$)/g) || [normalized];
    const chunks = [];
    let currentSentences = [];
    let currentWords = 0;

    const flushCurrent = () => {
        if (!currentSentences.length) return;
        chunks.push(
            currentSentences
                .join(' ')
                .replace(/\s{2,}/g, ' ')
                .trim(),
        );
        currentSentences = [];
        currentWords = 0;
    };

    const pushByWords = (segment) => {
        const words = segment.split(/\s+/).filter(Boolean);
        for (let index = 0; index < words.length; index += maxWords) {
            chunks.push(words.slice(index, index + maxWords).join(' '));
        }
    };

    for (const rawPart of sentenceParts) {
        const part = rawPart.replace(/\s+/g, ' ').trim();
        if (!part) continue;

        const partWords = countWords(part);
        if (partWords > maxWords) {
            flushCurrent();
            pushByWords(part);
            continue;
        }

        if (currentWords + partWords > maxWords && currentSentences.length) {
            flushCurrent();
        }

        currentSentences.push(part);
        currentWords += partWords;
    }

    flushCurrent();
    return chunks.length ? chunks : [normalized];
}

function splitParagraphWithOffsets(paragraph, maxWords) {
    const chunkTexts = splitLongParagraph(paragraph.text, maxWords);
    if (!chunkTexts.length) return [];
    if (chunkTexts.length === 1) {
        return [
            {
                text: chunkTexts[0],
                charStart: paragraph.charStart,
                charEnd: paragraph.charEnd,
                lineStart: paragraph.lineStart,
                lineEnd: paragraph.lineEnd,
            },
        ];
    }

    const paragraphWords = Math.max(1, countWords(paragraph.text));
    const spanChars = Math.max(1, (paragraph.charEnd || 0) - (paragraph.charStart || 0));
    const spanLines = Math.max(1, (paragraph.lineEnd || 1) - (paragraph.lineStart || 1) + 1);

    let consumedWords = 0;
    return chunkTexts.map((chunkText, chunkIndex) => {
        const words = Math.max(1, countWords(chunkText));
        const startRatio = consumedWords / paragraphWords;
        consumedWords += words;
        const endRatio = Math.min(1, consumedWords / paragraphWords);

        const charStart = Math.round((paragraph.charStart || 0) + spanChars * startRatio);
        const estimatedCharEnd = Math.round((paragraph.charStart || 0) + spanChars * endRatio);
        const charEnd =
            chunkIndex === chunkTexts.length - 1
                ? (paragraph.charEnd || estimatedCharEnd)
                : Math.max(charStart + 1, estimatedCharEnd);

        const lineStart = Math.max(
            1,
            Math.round((paragraph.lineStart || 1) + (spanLines - 1) * startRatio),
        );
        const estimatedLineEnd = Math.max(
            lineStart,
            Math.round((paragraph.lineStart || 1) + (spanLines - 1) * endRatio),
        );
        const lineEnd = chunkIndex === chunkTexts.length - 1
            ? Math.max(lineStart, paragraph.lineEnd || estimatedLineEnd)
            : estimatedLineEnd;

        return {
            text: chunkText,
            charStart,
            charEnd,
            lineStart,
            lineEnd,
        };
    });
}

function isProbableChapterHeading(value) {
    const text = String(value || '').trim();
    if (!text) return false;
    if (text.length > 120) return false;

    if (
        /^(глава|chapter|часть|part)\s+([ivxlcdm]+|\d+|[а-яёa-z]+)(?:\s+[а-яёa-z]+){0,2}\s*[.:)\-]?\s*$/iu.test(
            text,
        )
    ) {
        return true;
    }

    if (/^(пролог|эпилог)\b[.:)\-]?\s*.*$/iu.test(text)) {
        return true;
    }

    if (/^[IVXLCDM]{1,8}[.)-]?$/i.test(text)) {
        return true;
    }

    return false;
}

function capitalizeFirst(value) {
    const text = String(value || '');
    if (!text) return '';
    return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

function isAllLettersUpper(value) {
    const letters = String(value || '').match(/[A-Za-zА-Яа-яЁё]/g);
    if (!letters || !letters.length) return false;
    return letters.every((char) => char === char.toUpperCase());
}

function normalizeChapterSuffix(value) {
    const trimmed = String(value || '')
        .replace(/[.:)\-]+$/u, '')
        .replace(/\s{2,}/g, ' ')
        .trim();

    if (!trimmed) return '';
    if (/^[IVXLCDM]+$/i.test(trimmed)) return trimmed.toUpperCase();
    if (/^\d+$/.test(trimmed)) return trimmed;
    if (isAllLettersUpper(trimmed)) return trimmed.toLowerCase();
    return trimmed;
}

function formatChapterTitle(rawTitle) {
    const cleaned = String(rawTitle || '')
        .replace(/\s{2,}/g, ' ')
        .trim();
    if (!cleaned) return '';

    const chapterMatch = cleaned.match(/^(глава|chapter)\s+(.+)$/iu);
    if (chapterMatch) {
        const suffix = normalizeChapterSuffix(chapterMatch[2]);
        return suffix ? `Глава ${suffix}` : 'Глава';
    }

    const partMatch = cleaned.match(/^(часть|part)\s+(.+)$/iu);
    if (partMatch) {
        const suffix = normalizeChapterSuffix(partMatch[2]);
        return suffix ? `Часть ${suffix}` : 'Часть';
    }

    const prologueEpilogueMatch = cleaned.match(/^(пролог|эпилог)\b/iu);
    if (prologueEpilogueMatch) {
        return capitalizeFirst(prologueEpilogueMatch[1].toLowerCase());
    }

    if (/^[IVXLCDM]{1,8}[.)-]?$/i.test(cleaned)) {
        const roman = cleaned.replace(/[.)-]$/g, '');
        return `Глава ${roman.toUpperCase()}`;
    }

    if (isAllLettersUpper(cleaned)) {
        return capitalizeFirst(cleaned.toLowerCase());
    }

    return cleaned;
}

function detectChapters(paragraphs) {
    const found = [];
    let previousHeadingIndex = -100;

    paragraphs.forEach((paragraph, index) => {
        if (!isProbableChapterHeading(paragraph.text)) {
            return;
        }

        if (index - previousHeadingIndex < 2) {
            return;
        }

        let title = formatChapterTitle(paragraph.text);
        if (title.length > 72) {
            title = `${title.slice(0, 69)}...`;
        }

        found.push({
            id: `chapter-${found.length + 1}`,
            title,
            paragraphIndex: index,
        });
        previousHeadingIndex = index;
    });

    return found;
}

function buildPagesFromParagraphs(paragraphs) {
    const wordsPerPage = getWordsPerPage();
    const result = [];
    let currentItems = [];
    let currentWords = 0;
    const flowItems = [];

    paragraphs.forEach((paragraph, index) => {
        const heading = isProbableChapterHeading(paragraph.text);
        if (heading) {
            flowItems.push({
                text: paragraph.text,
                index,
                heading: true,
                charStart: paragraph.charStart,
                charEnd: paragraph.charEnd,
                lineStart: paragraph.lineStart,
                lineEnd: paragraph.lineEnd,
            });
            return;
        }

        const parts = splitParagraphWithOffsets(paragraph, wordsPerPage);
        parts.forEach((part) => {
            flowItems.push({
                text: part.text,
                index,
                heading: false,
                charStart: part.charStart,
                charEnd: part.charEnd,
                lineStart: part.lineStart,
                lineEnd: part.lineEnd,
            });
        });
    });

    const flush = () => {
        if (!currentItems.length) return;

        const startParagraph = currentItems[0].index;
        const endParagraph = currentItems[currentItems.length - 1].index;
        const startChar =
            currentItems.find((item) => Number.isFinite(item.charStart))?.charStart ?? 0;
        const endChar =
            [...currentItems].reverse().find((item) => Number.isFinite(item.charEnd))?.charEnd ??
            startChar;
        const lineStart =
            currentItems.find((item) => Number.isFinite(item.lineStart))?.lineStart ?? 1;
        const lineEnd =
            [...currentItems].reverse().find((item) => Number.isFinite(item.lineEnd))?.lineEnd ??
            lineStart;
        const html = currentItems
            .map((item) => {
                if (item.heading) {
                    return `<h3 class="reader-heading">${escapeHtml(item.text)}</h3>`;
                }
                return `<p class="reader-paragraph">${escapeHtml(item.text)}</p>`;
            })
            .join('');

        result.push({
            html,
            startParagraph,
            endParagraph,
            startChar,
            endChar,
            lineStart,
            lineEnd,
        });

        currentItems = [];
        currentWords = 0;
    };

    flowItems.forEach((item) => {
        const heading = Boolean(item.heading);
        const words = Math.max(1, countWords(item.text));

        // Новый заголовок главы переносим на новую страницу только если текущая уже
        // заметно заполнена; это уменьшает пустые "хвосты" внизу страницы.
        const shouldStartHeadingOnNewPage =
            heading && currentItems.length > 0 && currentWords >= wordsPerPage * 0.72;
        if (shouldStartHeadingOnNewPage) {
            flush();
        }

        const overflow = currentItems.length > 0 && currentWords + words > wordsPerPage;
        const headingOnlyPage = currentItems.length === 1 && currentItems[0].heading;

        // Не оставляем заголовок главы сиротой внизу страницы:
        // если заголовок стоит последним элементом и следующий абзац не влезает,
        // переносим заголовок вместе с абзацем на следующую страницу.
        if (overflow && !heading) {
            const trailingItem = currentItems[currentItems.length - 1];
            const trailingHeadingOnCrowdedPage =
                currentItems.length > 1 && Boolean(trailingItem?.heading);

            if (trailingHeadingOnCrowdedPage) {
                const headingItem = currentItems.pop();
                flush();
                if (headingItem) {
                    currentItems.push(headingItem);
                    currentWords = Math.max(1, countWords(headingItem.text));
                }
            } else if (!headingOnlyPage) {
                flush();
            }
        }

        currentItems.push({
            text: item.text,
            index: item.index,
            heading,
            charStart: item.charStart,
            charEnd: item.charEnd,
            lineStart: item.lineStart,
            lineEnd: item.lineEnd,
        });
        currentWords += words;
    });

    flush();

    if (!result.length) {
        result.push({
            html: '<p class="reader-empty">Книга не содержит текста для отображения.</p>',
            startParagraph: 0,
            endParagraph: 0,
            startChar: 0,
            endChar: 0,
            lineStart: 1,
            lineEnd: 1,
        });
    }

    return result;
}

function mapChaptersToPages(chapterCandidates, pageItems) {
    const mapped = chapterCandidates
        .map((chapter) => {
            let page = 1;

            for (let index = 0; index < pageItems.length; index += 1) {
                const item = pageItems[index];
                if (chapter.paragraphIndex <= item.endParagraph) {
                    page = index + 1;
                    break;
                }
                page = index + 1;
            }

            return {
                ...chapter,
                page,
            };
        })
        .sort((a, b) => a.page - b.page);

    return mapped.filter((chapter, index, all) => {
        if (index === 0) return true;
        return chapter.page !== all[index - 1].page;
    });
}

function buildBookStructure(text) {
    const paragraphs = splitIntoParagraphs(text);
    const pageItems = buildPagesFromParagraphs(paragraphs);
    const chapterItems = mapChaptersToPages(detectChapters(paragraphs), pageItems);

    return {
        pageItems,
        chapterItems,
    };
}

function toFiniteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function rangesOverlap(startA, endA, startB, endB) {
    return startA <= endB && startB <= endA;
}

function findPageByLocation(location = {}) {
    if (!pages.length) return null;

    const startChar = toFiniteNumber(location.char_start);
    const endChar = toFiniteNumber(location.char_end);
    if (startChar !== null) {
        const safeEndChar = endChar !== null ? Math.max(startChar, endChar) : startChar;
        for (let index = 0; index < pages.length; index += 1) {
            const page = pages[index];
            const pageStart = toFiniteNumber(page.startChar);
            const pageEnd = toFiniteNumber(page.endChar);
            if (pageStart === null || pageEnd === null) continue;
            if (rangesOverlap(startChar, safeEndChar, pageStart, pageEnd)) {
                return index + 1;
            }
        }
    }

    const startLine = toFiniteNumber(location.line_start);
    const endLine = toFiniteNumber(location.line_end);
    if (startLine !== null) {
        const safeEndLine = endLine !== null ? Math.max(startLine, endLine) : startLine;
        for (let index = 0; index < pages.length; index += 1) {
            const page = pages[index];
            const pageStartLine = toFiniteNumber(page.lineStart);
            const pageEndLine = toFiniteNumber(page.lineEnd);
            if (pageStartLine === null || pageEndLine === null) continue;
            if (rangesOverlap(startLine, safeEndLine, pageStartLine, pageEndLine)) {
                return index + 1;
            }
        }
    }

    const chapterNumber = toFiniteNumber(location.chapter);
    if (chapterNumber !== null && chapters.length) {
        const chapterIndex = Math.max(1, Math.floor(chapterNumber)) - 1;
        const chapterItem = chapters[Math.min(chapters.length - 1, chapterIndex)];
        if (chapterItem?.page) {
            return chapterItem.page;
        }
    }

    return null;
}

function resolveSearchResultPage(result) {
    if (!result) return currentPage;
    const explicitPage = toFiniteNumber(result.page);
    if (explicitPage !== null && explicitPage > 0) {
        const safePage = Math.max(1, Math.min(totalPages || explicitPage, explicitPage));
        result.__resolvedPage = safePage;
        return safePage;
    }
    if (Number.isFinite(result.__resolvedPage) && result.__resolvedPage > 0) {
        return result.__resolvedPage;
    }

    const pageByLocation = findPageByLocation(result.location || {});
    const pageByText = findBestPageForSearchResult(result);
    const resolvedPage = pageByLocation || pageByText;

    result.__resolvedPage = Math.max(1, Math.min(totalPages || resolvedPage, resolvedPage));
    return result.__resolvedPage;
}

function stripTags(html) {
    return String(html || "").replace(/<[^>]*>/g, " ");
}

function normalizeForMatch(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/ё/g, "е")
        .replace(/[^a-zа-я0-9\s]/gi, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function getPagePlainText(pageIndex) {
    if (!pages[pageIndex]) return "";
    if (!pageTextCache[pageIndex]) {
        pageTextCache[pageIndex] = normalizeForMatch(stripTags(pages[pageIndex].html));
    }
    return pageTextCache[pageIndex];
}

function getPageSearchText(pageIndex) {
    if (!pages[pageIndex]) return '';
    if (!pageSearchTextCache[pageIndex]) {
        const container = document.createElement('div');
        container.innerHTML = String(pages[pageIndex].html || '');
        pageSearchTextCache[pageIndex] = container.textContent || '';
    }
    return pageSearchTextCache[pageIndex];
}

function buildSearchNeedles(result) {
    const needles = [];
    const fragment = normalizeForMatch(result?.fragment || "");
    const query = normalizeForMatch(result?.query || "");

    if (fragment) {
        needles.push(fragment);
        if (fragment.length > 180) {
            needles.push(fragment.slice(0, 180).trim());
        }
    }

    if (query && query.length >= 4) {
        needles.push(query);
    }

    return Array.from(new Set(needles.filter(Boolean))).sort((a, b) => b.length - a.length);
}

function findBestPageForSearchResult(result) {
    if (!pages.length) return 1;
    const needles = buildSearchNeedles(result);
    if (!needles.length) return currentPage;

    let bestPage = currentPage;
    let bestScore = -1;

    for (let pageIndex = 0; pageIndex < pages.length; pageIndex += 1) {
        const text = getPagePlainText(pageIndex);
        if (!text) continue;

        let score = 0;
        for (const needle of needles) {
            if (text.includes(needle)) {
                score = Math.max(score, needle.length * 3);
            } else {
                const tokens = needle.split(" ").filter((token) => token.length >= 3);
                if (!tokens.length) continue;
                const overlap = tokens.filter((token) => text.includes(token)).length;
                score = Math.max(score, overlap * 12);
            }
        }

        if (score > bestScore) {
            bestScore = score;
            bestPage = pageIndex + 1;
        }
    }

    return bestPage;
}

function isWordCharacter(char) {
    return Boolean(char) && /[\p{L}\p{N}_]/u.test(char);
}

function hasWholeWordBoundaries(text, start, end) {
    const source = String(text || '');
    if (start < 0 || end <= start || end > source.length) return false;
    const before = source[start - 1] || '';
    const after = source[end] || '';
    return !isWordCharacter(before) && !isWordCharacter(after);
}

function findStrictMatchesInText(
    text,
    query,
    { wholeWord = false, caseSensitive = false, maxMatches = Number.POSITIVE_INFINITY } = {},
) {
    const source = String(text || '');
    const needle = String(query || '');
    if (!source || !needle) return { matches: [], truncated: false };

    const haystack = caseSensitive ? source : source.toLowerCase();
    const target = caseSensitive ? needle : needle.toLowerCase();

    const matches = [];
    let cursor = 0;
    let truncated = false;

    while (cursor <= haystack.length - target.length) {
        const index = haystack.indexOf(target, cursor);
        if (index === -1) break;

        const end = index + target.length;
        const before = source[index - 1] || '';
        const after = source[end] || '';
        const boundaryOk =
            !wholeWord || (!isWordCharacter(before) && !isWordCharacter(after));

        if (boundaryOk) {
            matches.push({ start: index, end });
            if (matches.length >= maxMatches) {
                truncated = true;
                break;
            }
        }

        cursor = index + Math.max(1, target.length);
    }

    return { matches, truncated };
}

function buildStrictSearchHits(query, wholeWord) {
    const hits = [];
    let truncated = false;

    for (let pageIndex = 0; pageIndex < pages.length; pageIndex += 1) {
        const pageText = getPageSearchText(pageIndex);
        if (!pageText) continue;

        const remaining = Math.max(0, MAX_STRICT_SEARCH_MATCHES - hits.length);
        if (remaining <= 0) {
            truncated = true;
            break;
        }

        const { matches, truncated: pageTruncated } = findStrictMatchesInText(pageText, query, {
            wholeWord,
            caseSensitive: false,
            maxMatches: remaining,
        });

        matches.forEach((match) => {
            hits.push({
                fragment: pageText.slice(match.start, match.end),
                query,
                page: pageIndex + 1,
                __strict: true,
                __wholeWord: wholeWord,
                __localStart: match.start,
                __localEnd: match.end,
                __resolvedPage: pageIndex + 1,
            });
        });

        if (pageTruncated || hits.length >= MAX_STRICT_SEARCH_MATCHES) {
            truncated = true;
            break;
        }
    }

    return { hits, truncated };
}

function clearSearchHighlights() {
    const textLayer = document.getElementById('text-layer');
    if (!textLayer) return;

    textLayer.querySelectorAll('.search-highlight').forEach((mark) => {
        const parent = mark.parentNode;
        if (!parent) return;
        parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
        parent.normalize();
    });
}

function normalizeSpaces(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function escapeRegExp(value) {
    return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildPageTextIndex(rootNode) {
    const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
            return node.nodeValue && node.nodeValue.length
                ? NodeFilter.FILTER_ACCEPT
                : NodeFilter.FILTER_REJECT;
        },
    });

    const nodes = [];
    let offset = 0;
    let node = walker.nextNode();
    while (node) {
        const value = node.nodeValue || '';
        const length = value.length;
        nodes.push({
            node,
            text: value,
            start: offset,
            end: offset + length,
        });
        offset += length;
        node = walker.nextNode();
    }

    return {
        text: nodes.map((item) => item.text).join(''),
        nodes,
    };
}

function wrapTextRangeInNode(textNode, startOffset, endOffset) {
    const value = textNode.nodeValue || '';
    if (startOffset < 0 || endOffset > value.length || startOffset >= endOffset) {
        return null;
    }

    const before = value.slice(0, startOffset);
    const middle = value.slice(startOffset, endOffset);
    const after = value.slice(endOffset);
    if (!middle) return null;

    const fragment = document.createDocumentFragment();
    if (before) fragment.appendChild(document.createTextNode(before));

    const mark = document.createElement('mark');
    mark.className = 'search-highlight';
    mark.textContent = middle;
    fragment.appendChild(mark);

    if (after) fragment.appendChild(document.createTextNode(after));

    const parent = textNode.parentNode;
    if (!parent) return null;
    parent.replaceChild(fragment, textNode);
    return mark;
}

function applyHighlightRangeAcrossNodes(nodes, startIndex, endIndex) {
    const overlaps = [];
    nodes.forEach((item) => {
        if (endIndex <= item.start || startIndex >= item.end) return;
        overlaps.push({
            node: item.node,
            startOffset: Math.max(0, startIndex - item.start),
            endOffset: Math.min(item.end, endIndex) - item.start,
        });
    });

    if (!overlaps.length) return [];

    const marks = [];
    for (let index = overlaps.length - 1; index >= 0; index -= 1) {
        const overlap = overlaps[index];
        const mark = wrapTextRangeInNode(overlap.node, overlap.startOffset, overlap.endOffset);
        if (mark) {
            marks.push(mark);
        }
    }

    return marks.reverse();
}

function buildHighlightCandidates(result) {
    const candidates = [];
    const fragmentText = normalizeSpaces(result?.fragment || '');
    if (fragmentText.length >= 4) {
        candidates.push(fragmentText);
    }

    const location = result?.location || {};
    const startChar = toFiniteNumber(location.char_start);
    const endChar = toFiniteNumber(location.char_end);
    if (startChar !== null && endChar !== null && endChar > startChar) {
        const fromBook = normalizeSpaces(String(bookText || '').slice(startChar, endChar));
        if (fromBook.length >= 4) {
            candidates.unshift(fromBook);
        }
    }

    if (result?.query) {
        const query = normalizeSpaces(result.query);
        if (query.length >= 4) {
            candidates.push(query);
        }
    }

    return Array.from(new Set(candidates));
}

function findMatchByCandidate(pageText, candidate) {
    if (!pageText || !candidate) return null;
    const raw = normalizeSpaces(candidate);
    if (raw.length < 4) return null;

    const lowerPage = pageText.toLowerCase();
    const lowerRaw = raw.toLowerCase();
    const directIndex = lowerPage.indexOf(lowerRaw);
    if (directIndex >= 0) {
        return {
            start: directIndex,
            end: directIndex + raw.length,
        };
    }

    const tokens = raw.split(/\s+/).filter(Boolean);
    if (tokens.length >= 2) {
        const pattern = tokens.map((token) => escapeRegExp(token)).join('\\s+');
        try {
            const regex = new RegExp(pattern, 'i');
            const match = regex.exec(pageText);
            if (match) {
                return {
                    start: match.index,
                    end: match.index + match[0].length,
                };
            }
        } catch (error) {
            // invalid regex should not break search highlighting
        }
    }

    return null;
}

function findMatchRangeInPageText(pageText, result) {
    const candidates = buildHighlightCandidates(result);
    for (const candidate of candidates) {
        const match = findMatchByCandidate(pageText, candidate);
        if (match) return match;
    }

    const fallbackNeedles = buildSearchNeedles(result)
        .filter((needle) => needle.length >= 4)
        .map((needle) => needle.slice(0, 120).trim());
    for (const needle of fallbackNeedles) {
        const tokens = needle.split(/\s+/).filter((token) => token.length >= 3);
        if (tokens.length < 2) continue;
        const pattern = tokens.map((token) => escapeRegExp(token)).join('\\s+');
        try {
            const regex = new RegExp(pattern, 'i');
            const match = regex.exec(pageText);
            if (match) {
                return {
                    start: match.index,
                    end: match.index + match[0].length,
                };
            }
        } catch (error) {
            // ignore invalid fallback patterns
        }
    }

    return null;
}

function highlightStrictMatchOnCurrentPage(pageIndex, result) {
    const strictText = String(pageIndex.text || '');
    if (!strictText) return false;

    const preferredStart = toFiniteNumber(result?.__localStart);
    const preferredEnd = toFiniteNumber(result?.__localEnd);
    const strictNeedles = [result?.fragment, result?.query]
        .map((item) => String(item || '').trim())
        .filter(Boolean)
        .map((item) => item.toLowerCase());

    if (
        preferredStart !== null &&
        preferredEnd !== null &&
        preferredStart >= 0 &&
        preferredEnd > preferredStart &&
        preferredEnd <= strictText.length
    ) {
        const strictSlice = strictText.slice(preferredStart, preferredEnd).toLowerCase();
        const exactMatchOk = strictNeedles.length === 0 || strictNeedles.includes(strictSlice);
        const wholeWordOk =
            !result?.__wholeWord ||
            hasWholeWordBoundaries(strictText, preferredStart, preferredEnd);

        if (exactMatchOk && wholeWordOk) {
            const marks = applyHighlightRangeAcrossNodes(
                pageIndex.nodes,
                preferredStart,
                preferredEnd,
            );
            if (marks.length) {
                marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
                return true;
            }
        }
    }

    const query = String(result?.query || result?.fragment || '').trim();
    if (!query) return false;

    const { matches } = findStrictMatchesInText(pageIndex.text, query, {
        wholeWord: Boolean(result?.__wholeWord),
        caseSensitive: false,
        maxMatches: 5000,
    });
    if (!matches.length) return false;

    let selected = matches[0];
    if (preferredStart !== null) {
        const hint = Math.max(0, preferredStart);
        selected = matches.reduce((best, item) => {
            const currentDistance = Math.abs(item.start - hint);
            const bestDistance = Math.abs(best.start - hint);
            return currentDistance < bestDistance ? item : best;
        }, matches[0]);
    }

    const marks = applyHighlightRangeAcrossNodes(pageIndex.nodes, selected.start, selected.end);
    if (!marks.length) return false;
    marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
}

function applySearchHighlightForCurrentPage() {
    clearSearchHighlights();
    if (!activeSearchResult) return false;
    if (activeSearchResult.page !== currentPage) return false;

    const textLayer = document.getElementById('text-layer');
    if (!textLayer) return false;

    const pageIndex = buildPageTextIndex(textLayer);
    if (!pageIndex.text || !pageIndex.nodes.length) return false;

    if (activeSearchResult.__strict) {
        return highlightStrictMatchOnCurrentPage(pageIndex, activeSearchResult);
    }

    const match = findMatchRangeInPageText(pageIndex.text, activeSearchResult);
    if (!match) return false;

    const marks = applyHighlightRangeAcrossNodes(pageIndex.nodes, match.start, match.end);
    if (!marks.length) return false;

    marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
}

function renderSearchHitMarkers() {
    const strip = document.getElementById('search-hit-strip');
    if (!strip) return;

    strip.innerHTML = '';
    strip.classList.remove('active');
    readerSearchHitPages = [];
    readerSearchHitPageToIndex = new Map();

    if (!readerSearchHits.length || !totalPages) return;

    readerSearchHits.forEach((hit, hitIndex) => {
        const page = resolveSearchResultPage(hit);
        if (!Number.isFinite(page)) return;
        if (!readerSearchHitPageToIndex.has(page)) {
            readerSearchHitPageToIndex.set(page, hitIndex);
            readerSearchHitPages.push(page);
        }
    });

    readerSearchHitPages.sort((a, b) => a - b);
    if (!readerSearchHitPages.length) return;

    strip.classList.add('active');
    readerSearchHitPages.forEach((page) => {
        const marker = document.createElement('button');
        marker.type = 'button';
        marker.className = 'search-hit-marker';
        marker.title = `Совпадение на странице ${page}`;
        marker.style.left = `${((page - 0.5) / totalPages) * 100}%`;
        if (page === currentPage) {
            marker.classList.add('search-hit-marker--active');
        }

        marker.addEventListener('click', () => {
            const hitIndex = readerSearchHitPageToIndex.get(page);
            if (hitIndex !== undefined) {
                openReaderSearchHit(hitIndex);
            }
        });

        strip.appendChild(marker);
    });
}

function openSearchResultInReader(result) {
    if (!result || !pages.length) return false;

    const targetPage = resolveSearchResultPage(result);
    activeSearchResult = {
        ...result,
        page: targetPage,
    };

    displayPage(targetPage);
    const highlighted = applySearchHighlightForCurrentPage();
    if (!highlighted) {
        showChapterJumpHint('Фрагмент открыт в тексте (точное место не выделено)');
    } else {
        showChapterJumpHint('Фрагмент найден и подсвечен в тексте');
    }

    renderSearchHitMarkers();
    return true;
}

function setReaderSearchStatus(text, isError = false) {
    const statusNode = document.getElementById('reader-search-status');
    if (!statusNode) return;

    const normalizedText =
        typeof text === 'string' ? text : normalizeErrorMessage(text, '');
    statusNode.textContent = normalizedText || '';
    statusNode.classList.toggle('error', Boolean(isError));
}

function updateReaderSearchButtons() {
    const prevButton = document.getElementById('reader-search-prev');
    const nextButton = document.getElementById('reader-search-next');
    if (!prevButton || !nextButton) return;

    const hasHits = readerSearchHits.length > 0 && readerSearchIndex >= 0;
    prevButton.disabled = !hasHits || readerSearchIndex <= 0;
    nextButton.disabled = !hasHits || readerSearchIndex >= readerSearchHits.length - 1;
    renderSearchHitMarkers();
}

function openReaderSearchHit(index) {
    if (index < 0 || index >= readerSearchHits.length) return false;
    const fragment = readerSearchHits[index];
    if (!fragment) return false;

    const opened = openSearchResultInReader({
        ...fragment,
        query: readerSearchQuery,
    });
    if (!opened) return false;

    readerSearchIndex = index;
    const openedPage = activeSearchResult?.page || resolveSearchResultPage(fragment);
    const modeLabel = readerSearchWholeWord ? 'целые слова' : 'по символам';
    const truncatedSuffix = readerSearchTruncated
        ? ` (первые ${readerSearchHits.length})`
        : '';
    setReaderSearchStatus(
        `Открыто совпадение ${index + 1} из ${readerSearchHits.length}${truncatedSuffix} · ${modeLabel} · стр. ${openedPage}`,
    );
    updateReaderSearchButtons();
    return true;
}

function clearReaderSearchState() {
    clearSearchHighlights();
    activeSearchResult = null;
    readerSearchHits = [];
    readerSearchIndex = -1;
    readerSearchQuery = '';
    readerSearchWholeWord = false;
    readerSearchTruncated = false;
    readerSearchHitPages = [];
    readerSearchHitPageToIndex = new Map();
    updateReaderSearchButtons();
}

function toggleReaderSearchPanel(forceState) {
    const panel = document.getElementById('reader-search-panel');
    if (!panel) return;

    const shouldOpen =
        typeof forceState === 'boolean' ? forceState : !panel.classList.contains('active');
    panel.classList.toggle('active', shouldOpen);

    if (!shouldOpen) {
        const input = document.getElementById('reader-search-input');
        if (input) input.blur();
        return;
    }

    const sidePanel = document.getElementById('right-panel');
    const chaptersPanel = document.getElementById('chapters-panel');
    sidePanel?.classList.remove('visible');
    chaptersPanel?.classList.remove('active');

    const input = document.getElementById('reader-search-input');
    if (input) {
        setTimeout(() => input.focus(), 0);
    }
}

async function runReaderContextSearch() {
    const input = document.getElementById('reader-search-input');
    if (!input) return;
    const wholeWordCheckbox = document.getElementById('reader-search-whole-word');

    const query = input.value.trim();
    const wholeWord = Boolean(wholeWordCheckbox?.checked);
    if (!query) {
        setReaderSearchStatus('Введите текст для строгого поиска', true);
        clearReaderSearchState();
        return;
    }

    if (!bookText || !pages.length) {
        setReaderSearchStatus('Сначала откройте книгу', true);
        clearReaderSearchState();
        return;
    }

    setReaderSearchStatus('Ищу точные совпадения по символам...');
    clearReaderSearchState();

    try {
        const { hits, truncated } = buildStrictSearchHits(query, wholeWord);
        if (!hits.length) {
            setReaderSearchStatus(
                wholeWord
                    ? 'Точных совпадений (целые слова) не найдено'
                    : 'Точных совпадений не найдено',
            );
            clearReaderSearchState();
            return;
        }

        readerSearchHits = hits;
        readerSearchQuery = query;
        readerSearchWholeWord = wholeWord;
        readerSearchTruncated = truncated;
        readerSearchIndex = -1;
        renderSearchHitMarkers();

        if (!openReaderSearchHit(0)) {
            setReaderSearchStatus('Фрагменты найдены, но открыть в тексте не удалось', true);
        }
    } catch (error) {
        setReaderSearchStatus(normalizeErrorMessage(error, 'Ошибка поиска'), true);
        clearReaderSearchState();
    }
}

function initializeReaderSearch() {
    const toggleButton = document.getElementById('toggle-reader-search');
    const closeButton = document.getElementById('reader-search-close');
    const runButton = document.getElementById('reader-search-run');
    const prevButton = document.getElementById('reader-search-prev');
    const nextButton = document.getElementById('reader-search-next');
    const input = document.getElementById('reader-search-input');
    const panel = document.getElementById('reader-search-panel');

    if (!toggleButton || !panel) return;

    if (toggleButton.dataset.bound !== 'true') {
        toggleButton.dataset.bound = 'true';
        toggleButton.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            toggleReaderSearchPanel();
        });
    }

    if (closeButton && closeButton.dataset.bound !== 'true') {
        closeButton.dataset.bound = 'true';
        closeButton.addEventListener('click', () => toggleReaderSearchPanel(false));
    }

    if (runButton && runButton.dataset.bound !== 'true') {
        runButton.dataset.bound = 'true';
        runButton.addEventListener('click', () => {
            runReaderContextSearch();
        });
    }

    if (prevButton && prevButton.dataset.bound !== 'true') {
        prevButton.dataset.bound = 'true';
        prevButton.addEventListener('click', () => {
            openReaderSearchHit(Math.max(0, readerSearchIndex - 1));
        });
    }

    if (nextButton && nextButton.dataset.bound !== 'true') {
        nextButton.dataset.bound = 'true';
        nextButton.addEventListener('click', () => {
            openReaderSearchHit(Math.min(readerSearchHits.length - 1, readerSearchIndex + 1));
        });
    }

    if (input && input.dataset.bound !== 'true') {
        input.dataset.bound = 'true';
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                runReaderContextSearch();
            }
        });
    }

    if (document.body.dataset.readerSearchOutsideBound !== 'true') {
        document.body.dataset.readerSearchOutsideBound = 'true';
        document.addEventListener('click', (event) => {
            if (!panel.classList.contains('active')) return;
            if (panel.contains(event.target)) return;
            if (toggleButton.contains(event.target)) return;
            toggleReaderSearchPanel(false);
        });
    }

    if (document.body.dataset.readerSearchEscBound !== 'true') {
        document.body.dataset.readerSearchEscBound = 'true';
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                toggleReaderSearchPanel(false);
            }
        });
    }

    updateReaderSearchButtons();
}

function isEditableTarget(target) {
    if (!target) return false;
    if (target.isContentEditable) return true;
    const tagName = String(target.tagName || '').toLowerCase();
    return tagName === 'input' || tagName === 'textarea' || tagName === 'select';
}

function initializeReaderKeyboardShortcuts() {
    if (document.body.dataset.readerShortcutsBound === 'true') return;
    document.body.dataset.readerShortcutsBound = 'true';

    document.addEventListener('keydown', (event) => {
        const activeTarget = document.activeElement;
        const editing = isEditableTarget(activeTarget);

        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
            event.preventDefault();
            toggleReaderSearchPanel(true);
            const input = document.getElementById('reader-search-input');
            if (input) {
                input.focus();
                input.select();
            }
            return;
        }

        if (event.key === 'F3' && readerSearchHits.length) {
            event.preventDefault();
            if (event.shiftKey) {
                openReaderSearchHit(Math.max(0, readerSearchIndex - 1));
            } else {
                openReaderSearchHit(Math.min(readerSearchHits.length - 1, readerSearchIndex + 1));
            }
            return;
        }

        if (editing || event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            displayPage(currentPage - 1);
            return;
        }
        if (event.key === 'ArrowRight') {
            event.preventDefault();
            displayPage(currentPage + 1);
        }
    });
}

function getCurrentChapter() {
    if (!chapters.length) return null;

    let active = chapters[0];
    for (const chapter of chapters) {
        if (chapter.page <= currentPage) {
            active = chapter;
        } else {
            break;
        }
    }

    return active;
}

function getCurrentChapterIndex() {
    const currentChapter = getCurrentChapter();
    if (!currentChapter) return -1;
    return chapters.findIndex((chapter) => chapter.id === currentChapter.id);
}

function navigateChapterByOffset(offset) {
    if (!chapters.length) {
        showChapterJumpHint('Переход по главам недоступен: главы не найдены');
        return;
    }

    const currentIndex = getCurrentChapterIndex();
    const fallbackIndex = offset > 0 ? 0 : chapters.length - 1;
    const baseIndex = currentIndex >= 0 ? currentIndex : fallbackIndex;
    const targetIndex = baseIndex + offset;

    if (targetIndex < 0 || targetIndex >= chapters.length) {
        showChapterJumpHint(offset < 0 ? 'Это первая глава' : 'Это последняя глава');
        return;
    }

    const targetChapter = chapters[targetIndex];
    displayPage(targetChapter.page, {
        fromChapter: true,
        chapterTitle: targetChapter.title,
    });
}

function updatePageCount() {
    const pageCount = document.getElementById('page-count');
    if (pageCount) {
        pageCount.textContent = String(totalPages);
    }
}

function updateChapterBreadcrumb() {
    const breadcrumbChapter = document.getElementById('breadcrumb-chapter');
    const chapter = getCurrentChapter();

    if (breadcrumbChapter) {
        breadcrumbChapter.textContent = chapter
            ? chapter.title
            : 'Глава не обнаружена';
    }
}

function updateChapterSelection() {
    const activeChapter = getCurrentChapter();

    document
        .querySelectorAll('#chapters-list .chapter-button')
        .forEach((button) => {
            const isActive =
                Boolean(activeChapter) &&
                button.dataset.chapterId === activeChapter.id;
            button.classList.toggle('chapter-button--active', isActive);
        });

    updateChapterNavButtons();
}

function updateChapterNavButtons() {
    const prevChapterBtn = document.getElementById('prev-chapter');
    const nextChapterBtn = document.getElementById('next-chapter');

    if (!prevChapterBtn || !nextChapterBtn) return;

    if (!chapters.length) {
        prevChapterBtn.disabled = true;
        nextChapterBtn.disabled = true;
        return;
    }

    const currentIndex = getCurrentChapterIndex();
    if (currentIndex < 0) {
        prevChapterBtn.disabled = true;
        nextChapterBtn.disabled = true;
        return;
    }

    prevChapterBtn.disabled = currentIndex <= 0;
    nextChapterBtn.disabled = currentIndex >= chapters.length - 1;
}

function showChapterJumpHint(message) {
    const hint = document.getElementById('chapter-jump-hint');
    if (!hint) return;

    hint.textContent = message;
    hint.classList.add('visible');

    if (chapterHintTimer) {
        clearTimeout(chapterHintTimer);
    }

    chapterHintTimer = setTimeout(() => {
        hint.classList.remove('visible');
    }, 1800);
}

function displayPage(pageNum, options = {}) {
    if (!Number.isFinite(pageNum)) return;
    if (!pages.length) return;

    const safePage = Math.max(1, Math.min(totalPages, Math.floor(pageNum)));
    const textLayer = document.getElementById('text-layer');
    if (!textLayer) return;

    currentPage = safePage;

    const page = pages[safePage - 1];
    textLayer.innerHTML = `<div class="page-content">${page.html}</div>`;

    const pageInput = document.getElementById('page-input');
    if (pageInput) {
        pageInput.value = String(currentPage);
    }

    const urlBookId = new URLSearchParams(window.location.search).get('id');
    if (urlBookId) {
        localStorage.setItem(`book_${urlBookId}_page`, String(currentPage));
    }

    updateReadingProgress();
    updateChapterBreadcrumb();
    updateChapterSelection();
    applySearchHighlightForCurrentPage();
    renderSearchHitMarkers();

    if (options.fromChapter && options.chapterTitle) {
        showChapterJumpHint(`Переход: ${options.chapterTitle}`);
    }
}

function applyPendingReaderJump(bookId) {
    let pendingRaw = "";
    try {
        pendingRaw = localStorage.getItem("bookversePendingReaderJump") || "";
    } catch (error) {
        pendingRaw = "";
    }
    if (!pendingRaw) return false;

    let payload = null;
    try {
        payload = JSON.parse(pendingRaw);
    } catch (error) {
        localStorage.removeItem("bookversePendingReaderJump");
        return false;
    }

    const targetBookId = Number(payload?.bookId);
    const currentBookId = Number(bookId);
    if (Number.isFinite(targetBookId) && Number.isFinite(currentBookId) && targetBookId !== currentBookId) {
        return false;
    }

    const result = payload?.result || {};
    if (payload?.chapter && (!result.location || result.location.chapter == null)) {
        result.location = {
            ...(result.location || {}),
            chapter: payload.chapter,
        };
    }

    localStorage.removeItem("bookversePendingReaderJump");
    if (!result || !Object.keys(result).length) return false;
    return openSearchResultInReader(result);
}

async function saveProgress(bookId, progress) {
    try {
        const response = await apiFetch(`/books/${bookId}/progress`, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${getAuthToken()}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ progress: parseInt(progress, 10) }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(normalizeErrorMessage(error, 'Failed to save progress'));
        }
    } catch (error) {
        console.error('Error saving progress:', error);
    }
}

function updateReadingProgress() {
    const percentageElement = document.getElementById('progress-percentage');
    const denominator = Math.max(1, totalPages);
    const percentage = Math.round((currentPage / denominator) * 100);

    if (percentageElement) {
        percentageElement.textContent = `${percentage}%`;
    }

    const bookId = new URLSearchParams(window.location.search).get('id');
    if (bookId && !Number.isNaN(parseInt(bookId, 10))) {
        saveProgress(bookId, percentage);
    }
}

function renderChapterList() {
    const chaptersList = document.getElementById('chapters-list');
    if (!chaptersList) return;

    chaptersList.innerHTML = '';

    if (!chapters.length) {
        chaptersList.innerHTML = '<p class="no-chapters">В тексте не найдены явные главы</p>';
        updateChapterNavButtons();
        return;
    }

    const list = document.createElement('ul');
    list.className = 'chapters-list-items';

    chapters.forEach((chapter, index) => {
        const item = document.createElement('li');

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'chapter-button';
        button.dataset.chapterId = chapter.id;

        const number = document.createElement('span');
        number.className = 'chapter-number';
        number.textContent = String(index + 1);

        const title = document.createElement('span');
        title.className = 'chapter-title';
        title.textContent = chapter.title;

        button.append(number, title);

        button.addEventListener('click', () => {
            displayPage(chapter.page, {
                fromChapter: true,
                chapterTitle: chapter.title,
            });
            toggleChapters(false);
        });

        item.appendChild(button);
        list.appendChild(item);
    });

    chaptersList.appendChild(list);
    updateChapterSelection();
}

function toggleChapters(forceState) {
    const chaptersPanel = document.getElementById('chapters-panel');
    if (!chaptersPanel) return;

    const shouldOpen =
        typeof forceState === 'boolean'
            ? forceState
            : !chaptersPanel.classList.contains('active');

    chaptersPanel.classList.toggle('active', shouldOpen);

    if (shouldOpen) {
        const sidePanel = document.getElementById('right-panel');
        sidePanel?.classList.remove('visible');
    }
}

function initializeNavigation() {
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    const pageInput = document.getElementById('page-input');
    const prevChapterBtn = document.getElementById('prev-chapter');
    const nextChapterBtn = document.getElementById('next-chapter');

    if (prevBtn && prevBtn.dataset.bound !== 'true') {
        prevBtn.dataset.bound = 'true';
        prevBtn.addEventListener('click', () => {
            displayPage(currentPage - 1);
        });
    }

    if (nextBtn && nextBtn.dataset.bound !== 'true') {
        nextBtn.dataset.bound = 'true';
        nextBtn.addEventListener('click', () => {
            displayPage(currentPage + 1);
        });
    }

    if (pageInput && pageInput.dataset.bound !== 'true') {
        pageInput.dataset.bound = 'true';
        pageInput.addEventListener('change', () => {
            const page = parseInt(pageInput.value, 10);
            if (Number.isFinite(page)) {
                displayPage(page);
            } else {
                pageInput.value = String(currentPage);
            }
        });
    }

    if (prevChapterBtn && prevChapterBtn.dataset.bound !== 'true') {
        prevChapterBtn.dataset.bound = 'true';
        prevChapterBtn.addEventListener('click', () => {
            navigateChapterByOffset(-1);
        });
    }

    if (nextChapterBtn && nextChapterBtn.dataset.bound !== 'true') {
        nextChapterBtn.dataset.bound = 'true';
        nextChapterBtn.addEventListener('click', () => {
            navigateChapterByOffset(1);
        });
    }
}

function initializeChapterPanel() {
    const toggleChaptersBtn = document.getElementById('toggle-chapters');
    const closeChaptersBtn = document.getElementById('close-chapters');
    const chaptersPanel = document.getElementById('chapters-panel');

    if (!toggleChaptersBtn || !chaptersPanel) return;

    if (toggleChaptersBtn.dataset.bound !== 'true') {
        toggleChaptersBtn.dataset.bound = 'true';
        toggleChaptersBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            toggleChapters();
        });
    }

    if (closeChaptersBtn && closeChaptersBtn.dataset.bound !== 'true') {
        closeChaptersBtn.dataset.bound = 'true';
        closeChaptersBtn.addEventListener('click', () => toggleChapters(false));
    }

    if (document.body.dataset.chaptersOutsideBound !== 'true') {
        document.body.dataset.chaptersOutsideBound = 'true';
        document.addEventListener('click', (event) => {
            if (!chaptersPanel.classList.contains('active')) return;
            if (chaptersPanel.contains(event.target)) return;
            if (toggleChaptersBtn.contains(event.target)) return;
            toggleChapters(false);
        });
    }

    if (document.body.dataset.chaptersEscBound !== 'true') {
        document.body.dataset.chaptersEscBound = 'true';
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                toggleChapters(false);
            }
        });
    }
}

async function loadBook() {
    const bookId = new URLSearchParams(window.location.search).get('id');

    if (!bookId) {
        const textLayer = document.getElementById('text-layer');
        if (textLayer) {
            textLayer.innerHTML = '<p class="reader-empty">Не указан идентификатор книги.</p>';
        }
        return;
    }

    try {
        const response = await apiFetch(`/books/${bookId}`, {
            headers: {
                Authorization: `Bearer ${getAuthToken()}`,
            },
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(normalizeErrorMessage(payload, 'Не удалось загрузить книгу'));
        }

        const data = await response.json();
        bookText = String(data.content || '');
        localStorage.setItem('bookText', bookText);
        localStorage.setItem('currentBookId', String(bookId));

        const structure = buildBookStructure(bookText);
        pages = structure.pageItems;
        chapters = structure.chapterItems;
        totalPages = pages.length;
        pageTextCache = [];
        pageSearchTextCache = [];
        activeSearchResult = null;
        clearReaderSearchState();

        renderChapterList();
        updatePageCount();

        const savedPage = parseInt(localStorage.getItem(`book_${bookId}_page`) || '1', 10);
        currentPage = Number.isFinite(savedPage)
            ? Math.max(1, Math.min(savedPage, totalPages))
            : 1;

        displayPage(currentPage);
        applyPendingReaderJump(bookId);
    } catch (error) {
        console.error('Error loading book:', error);
        const textLayer = document.getElementById('text-layer');
        if (textLayer) {
            textLayer.innerHTML = `
                <div class="error-message">
                    Ошибка загрузки книги: ${escapeHtml(
                        normalizeErrorMessage(error, 'попробуйте позже'),
                    )}
                </div>
            `;
        }
    }
}

window.toggleChapters = toggleChapters;
window.openSearchResultInReader = openSearchResultInReader;
window.toggleReaderSearchPanel = toggleReaderSearchPanel;

document.addEventListener('DOMContentLoaded', () => {
    initializeNavigation();
    initializeChapterPanel();
    initializeReaderSearch();
    initializeReaderKeyboardShortcuts();
    loadBook();
});
