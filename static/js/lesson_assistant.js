(() => {
  const root = document.getElementById('lesson-assistant');
  if (!root) return;

  const form = document.getElementById('assistant-form');
  const input = document.getElementById('assistant-question');
  const log = document.getElementById('assistant-messages');
  const loading = document.getElementById('assistant-loading');
  const submit = form.querySelector('button[type="submit"]');
  const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]')?.value;

  const add = (label, message) => {
    const paragraph = document.createElement('p');
    const strong = document.createElement('strong');
    strong.textContent = `${label}: `;
    paragraph.append(strong, document.createTextNode(message));
    log.append(paragraph);
    log.scrollTop = log.scrollHeight;
  };

  async function ask(question) {
    const cleanQuestion = question.trim();
    if (!cleanQuestion || loading.hidden === false) return;

    add('Vous', cleanQuestion);
    loading.hidden = false;
    submit.disabled = true;
    try {
      const response = await fetch(root.dataset.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          lesson_id: Number(root.dataset.lessonId),
          question: cleanQuestion,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        add('Assistant', data.error || `Erreur serveur (${response.status}).`);
        return;
      }
      add('Assistant', [data.answer, data.notice].filter(Boolean).join('\n'));
    } catch (error) {
      add('Assistant', 'Impossible de joindre le service. Vérifiez votre connexion et réessayez.');
    } finally {
      loading.hidden = true;
      submit.disabled = false;
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const question = input.value;
    input.value = '';
    ask(question);
  });

  document.querySelectorAll('.assistant-suggest').forEach((button) => {
    button.addEventListener('click', () => ask(button.dataset.question || ''));
  });
})();
