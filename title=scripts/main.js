export function createChapterList() {
    const chaptersListDiv = document.getElementById('chapters-list');
    if (!chaptersListDiv) return;

    chaptersListDiv.innerHTML = '';

    if (chapters.length === 0) {
        chaptersListDiv.innerHTML = '<p class="no-chapters">Главы не найдены</p>';
        return;
    }

    const ul = document.createElement('ul');
    ul.className = 'chapters-list-items';

    chapters.forEach((chapter, index) => {
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.className = 'chapter-button';
        button.innerHTML = `
            <span class="chapter-number">${index + 1}</span>
            <span class="chapter-title">${chapter.title}</span>
        `;
        
        button.addEventListener('click', () => {
            displayPage(chapter.page);
            const chaptersPanel = document.getElementById('chapters-panel');
            if (chaptersPanel) {
                chaptersPanel.classList.remove('active');
            }
        });

        li.appendChild(button);
        ul.appendChild(li);
    });

    chaptersListDiv.appendChild(ul);
} 