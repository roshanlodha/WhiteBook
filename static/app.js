const STORAGE_KEY = 'whitebook.chat.sessions.v1';
const ACTIVE_SESSION_KEY = 'whitebook.chat.activeSessionId.v1';

const appShell = document.querySelector('.app-shell');
const sidebar = document.getElementById('session-sidebar');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');
const sidebarToggle = document.getElementById('sidebar-toggle');
const newSessionButton = document.getElementById('new-session-button');
const sessionList = document.getElementById('session-list');
const chatHistory = document.getElementById('chat-history');
const chatForm = document.getElementById('chat-form');
const queryInput = document.getElementById('query-input');
const sendButton = document.getElementById('send-button');

const appState = {
	sessions: [],
	activeSessionId: null,
};

const THINK_LABEL = 'Thought for 70 seconds';

if (typeof marked !== 'undefined') {
	marked.setOptions({ gfm: true, breaks: true });
}

function loadStoredSessions() {
	try {
		const storedSessions = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
		if (Array.isArray(storedSessions) && storedSessions.length > 0) {
			appState.sessions = storedSessions;
		}

		appState.activeSessionId = localStorage.getItem(ACTIVE_SESSION_KEY);
	} catch {
		appState.sessions = [];
		appState.activeSessionId = null;
	}
}

function persistSessions() {
	localStorage.setItem(STORAGE_KEY, JSON.stringify(appState.sessions));
	if (appState.activeSessionId) {
		localStorage.setItem(ACTIVE_SESSION_KEY, appState.activeSessionId);
	} else {
		localStorage.removeItem(ACTIVE_SESSION_KEY);
	}
}

function createSession(title = 'New session') {
	const now = Date.now();
	return {
		id: crypto.randomUUID(),
		title,
		createdAt: now,
		updatedAt: now,
		messages: [],
	};
}

function ensureSessionState() {
	if (appState.sessions.length === 0) {
		const session = createSession();
		appState.sessions = [session];
		appState.activeSessionId = session.id;
		persistSessions();
		return;
	}

	const activeSessionExists = appState.sessions.some((session) => session.id === appState.activeSessionId);
	if (!activeSessionExists) {
		appState.activeSessionId = appState.sessions[0].id;
		persistSessions();
	}
}

function getActiveSession() {
	return appState.sessions.find((session) => session.id === appState.activeSessionId) || null;
}

function getSessionPreview(session) {
	const lastUserMessage = [...session.messages].reverse().find((message) => message.role === 'user');
	if (lastUserMessage?.content) {
		return lastUserMessage.content;
	}

	return 'No messages yet';
}

function updateSessionTimestamp(session) {
	session.updatedAt = Date.now();
}

function updateSessionTitle(session, query) {
	if (!session.title || session.title === 'New session' || session.messages.length <= 1) {
		const trimmed = query.trim();
		session.title = trimmed.length > 42 ? `${trimmed.slice(0, 42).trim()}…` : trimmed;
	}
}

function scrollToBottom() {
	chatHistory.scrollTop = chatHistory.scrollHeight;
}

function createMessageElement(role) {
	const element = document.createElement('div');
	element.className = `message ${role}`;
	return element;
}

function createMarkdownContainer(content) {
	const container = document.createElement('div');
	container.className = 'markdown-body';
	container.innerHTML = typeof marked !== 'undefined' ? marked.parse(content || '') : content || '';
	return container;
}

function splitThinkParagraphs(text) {
	return text
		.split(/\n\s*\n/)
		.map((paragraph) => paragraph.trim())
		.filter(Boolean);
}

function createThinkParagraphElement(paragraphText, index, isOpen) {
	const details = document.createElement('details');
	details.className = 'think-paragraph';
	details.open = isOpen;

	const summary = document.createElement('summary');
	summary.textContent = THINK_LABEL;
	details.appendChild(summary);

	const content = document.createElement('div');
	content.className = 'think-content';
	content.textContent = paragraphText;
	details.appendChild(content);

	return details;
}

function renderThinkThread(text, isComplete) {
	const thread = document.createElement('div');
	thread.className = 'think-thread';

	const paragraphs = splitThinkParagraphs(text);
	if (paragraphs.length === 0) {
		return thread;
	}

	for (let index = 0; index < paragraphs.length; index += 1) {
		const isLast = index === paragraphs.length - 1;
		thread.appendChild(createThinkParagraphElement(paragraphs[index], index, !isComplete && isLast));
	}

	return thread;
}

function updateThinkThread(container, text, isComplete) {
	container.replaceChildren(renderThinkThread(text, isComplete));
	if (text.trim().length === 0) {
		container.hidden = true;
	} else {
		container.hidden = false;
	}
}

function appendMessage(role, text = '') {
	const element = createMessageElement(role);
	element.textContent = text;
	chatHistory.appendChild(element);
	scrollToBottom();
	return element;
}

function appendStreamContainer(parent, isThinkMode) {
	const block = document.createElement('div');
	block.className = isThinkMode ? 'think-block' : 'answer-block';
	parent.appendChild(block);
	return block;
}

function appendAssistantMessage(message, options = {}) {
	const assistantBubble = createMessageElement('assistant');
	const answerContainer = document.createElement('div');
	answerContainer.className = 'assistant-answer';
	answerContainer.appendChild(createMarkdownContainer(message.content || ''));
	assistantBubble.appendChild(answerContainer);

	if (message.thinkContent) {
		const thinkContainer = document.createElement('div');
		thinkContainer.className = 'think-thread';
		updateThinkThread(thinkContainer, message.thinkContent, true);
		assistantBubble.appendChild(thinkContainer);
	}

	if (Array.isArray(options.imageFilenames) && options.imageFilenames.length > 0) {
		assistantBubble.appendChild(createReferenceImages(options.imageFilenames));
	}

	chatHistory.appendChild(assistantBubble);
	scrollToBottom();
	return assistantBubble;
}

function createReferenceImages(imageFilenames) {
	const references = document.createElement('div');
	references.className = 'reference-images';

	const label = document.createElement('p');
	label.className = 'reference-label';
	label.textContent = 'Retrieved image references';
	references.appendChild(label);

	for (const imageFilename of imageFilenames) {
		const figure = document.createElement('figure');
		figure.className = 'reference-card';

		const image = document.createElement('img');
		image.src = `/static/images/${imageFilename}`;
		image.alt = `Retrieved reference ${imageFilename}`;
		image.loading = 'lazy';
		figure.appendChild(image);

		const caption = document.createElement('figcaption');
		caption.textContent = imageFilename;
		figure.appendChild(caption);

		references.appendChild(figure);
	}

	return references;
}

function renderSessionList() {
	sessionList.innerHTML = '';
	const orderedSessions = [...appState.sessions].sort((left, right) => right.updatedAt - left.updatedAt);

	for (const session of orderedSessions) {
		const button = document.createElement('button');
		button.type = 'button';
		button.className = `session-item ${session.id === appState.activeSessionId ? 'active' : ''}`;
		button.setAttribute('role', 'listitem');

		const title = document.createElement('span');
		title.className = 'session-title';
		title.textContent = session.title || 'New session';
		button.appendChild(title);

		const preview = document.createElement('span');
		preview.className = 'session-preview';
		preview.textContent = getSessionPreview(session);
		button.appendChild(preview);

		button.addEventListener('click', () => switchSession(session.id));
		sessionList.appendChild(button);
	}
}

function renderSessionMessages(session) {
	chatHistory.innerHTML = '';
	for (const message of session.messages) {
		if (message.role === 'assistant') {
			appendAssistantMessage(message, { imageFilenames: message.imageFilenames || [] });
			continue;
		}

		appendMessage(message.role, message.content);
	}

	if (session.messages.length === 0) {
		const emptyState = document.createElement('div');
		emptyState.className = 'message system empty-state';
		emptyState.textContent = 'Start a session by asking a clinical question.';
		chatHistory.appendChild(emptyState);
	}

	scrollToBottom();
}

function closeSidebar() {
	appShell.classList.remove('sidebar-open');
	sidebarBackdrop.hidden = true;
}

function openSidebar() {
	appShell.classList.add('sidebar-open');
	sidebarBackdrop.hidden = false;
}

function switchSession(sessionId) {
	const session = appState.sessions.find((item) => item.id === sessionId);
	if (!session) {
		return;
	}

	appState.activeSessionId = sessionId;
	persistSessions();
	renderSessionList();
	renderSessionMessages(session);
	closeSidebar();
}

function createNewSession() {
	const session = createSession();
	appState.sessions.unshift(session);
	appState.activeSessionId = session.id;
	persistSessions();
	renderSessionList();
	renderSessionMessages(session);
	closeSidebar();
}

function autoResizeTextarea() {
	queryInput.style.height = 'auto';
	queryInput.style.height = `${Math.min(queryInput.scrollHeight, 220)}px`;
}

function parseSSEChunk(buffer) {
	const events = [];
	let remaining = buffer.replace(/\r\n/g, '\n');

	while (true) {
		const separatorIndex = remaining.indexOf('\n\n');
		if (separatorIndex === -1) {
			break;
		}

		const rawEvent = remaining.slice(0, separatorIndex);
		remaining = remaining.slice(separatorIndex + 2);

		const lines = rawEvent.split(/\r?\n/);
		let eventName = 'message';
		const dataLines = [];

		for (const line of lines) {
			if (line.startsWith('event:')) {
				eventName = line.slice(6).trim();
				continue;
			}

			if (line.startsWith('data:')) {
				dataLines.push(line.slice(5).replace(/^\s/, ''));
			}
		}

		if (dataLines.length > 0) {
			events.push({ event: eventName, data: dataLines.join('\n') });
		}
	}

	return { events, remaining };
}

function splitThinkTags(text, state) {
	const segments = [];
	const openTag = '<think>';
	const closeTag = '</think>';
	let buffer = (state.buffer || '') + text;
	let inThinkMode = state.inThinkMode;

	const pushSegment = (mode, content) => {
		if (content.length > 0) {
			segments.push({ mode, content });
		}
	};

	const suffixPrefixLength = (value, marker) => {
		const maxLength = Math.min(value.length, marker.length - 1);
		for (let length = maxLength; length > 0; length -= 1) {
			if (marker.startsWith(value.slice(value.length - length))) {
				return length;
			}
		}

		return 0;
	};

	while (buffer.length > 0) {
		if (!inThinkMode) {
			const openIndex = buffer.indexOf(openTag);
			if (openIndex === -1) {
				const carryLength = suffixPrefixLength(buffer, openTag);
				const emit = buffer.slice(0, buffer.length - carryLength);
				pushSegment('answer', emit);
				buffer = buffer.slice(buffer.length - carryLength);
				break;
			}

			pushSegment('answer', buffer.slice(0, openIndex));
			buffer = buffer.slice(openIndex + openTag.length);
			inThinkMode = true;
			continue;
		}

		const closeIndex = buffer.indexOf(closeTag);
		if (closeIndex === -1) {
			const carryLength = suffixPrefixLength(buffer, closeTag);
			const emit = buffer.slice(0, buffer.length - carryLength);
			pushSegment('think', emit);
			buffer = buffer.slice(buffer.length - carryLength);
			break;
		}

		pushSegment('think', buffer.slice(0, closeIndex));
		buffer = buffer.slice(closeIndex + closeTag.length);
		inThinkMode = false;
	}

	state.inThinkMode = inThinkMode;
	state.buffer = buffer;
	return segments;
}

async function retrieveContext(query) {
	const response = await fetch('/api/retrieve', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ query }),
	});

	if (!response.ok) {
		throw new Error(`Retrieval failed with status ${response.status}`);
	}

	const payload = await response.json();
	return Array.isArray(payload?.results) ? payload.results : [];
}

function buildHistoryPayload(session) {
	return session.messages
		.filter((message) => message.role === 'user' || message.role === 'assistant')
		.map((message) => ({ role: message.role, content: message.content }))
		.slice(-20);
}

async function sendMessage(query) {
	const session = getActiveSession();
	if (!session) {
		throw new Error('No active session available.');
	}

	const userMessage = { role: 'user', content: query };
	session.messages.push(userMessage);
	updateSessionTitle(session, query);
	updateSessionTimestamp(session);
	persistSessions();
	renderSessionList();

	const userBubble = appendMessage('user', query);
	const assistantBubble = createMessageElement('assistant');
	const answerContainer = document.createElement('div');
	answerContainer.className = 'assistant-answer';
	assistantBubble.appendChild(answerContainer);
	chatHistory.appendChild(assistantBubble);
	scrollToBottom();

	let retrievedResults = [];
	let assistantFinalAnswer = '';
	let assistantThinkText = '';
	let currentMarkdownContainer = null;
	let currentThinkContainer = null;
	let imageFilenames = [];

	try {
		retrievedResults = await retrieveContext(query);

		const response = await fetch('/api/chat', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				query,
				history: buildHistoryPayload(session).slice(0, -1),
			}),
		});

		if (!response.ok || !response.body) {
			throw new Error(`Request failed with status ${response.status}`);
		}

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = '';
		const parserState = { inThinkMode: false, buffer: '' };

		const appendToBlock = (mode, content) => {
			if (!content) {
				return;
			}

			if (mode === 'answer') {
				assistantFinalAnswer += content;
				if (!currentMarkdownContainer) {
					currentMarkdownContainer = document.createElement('div');
					currentMarkdownContainer.className = 'markdown-body streaming';
					answerContainer.appendChild(currentMarkdownContainer);
				}

				currentMarkdownContainer.textContent = assistantFinalAnswer;
				return;
			}

			assistantThinkText += content;
			if (!currentThinkContainer) {
				currentThinkContainer = document.createElement('div');
				currentThinkContainer.className = 'think-thread';
				answerContainer.appendChild(currentThinkContainer);
			}

			updateThinkThread(currentThinkContainer, assistantThinkText, false);
		};

		const processText = (text) => {
			const segments = splitThinkTags(text, parserState);
			for (const segment of segments) {
				appendToBlock(segment.mode, segment.content);
			}
		};

		while (true) {
			const { value, done } = await reader.read();
			if (done) {
				break;
			}

			buffer += decoder.decode(value, { stream: true });
			const parsed = parseSSEChunk(buffer);
			buffer = parsed.remaining;

			for (const event of parsed.events) {
				if (event.event === 'start') {
					continue;
				}

				if (event.event === 'done' || event.data === '[DONE]') {
					continue;
				}

				if (event.event === 'error') {
					let message = event.data;
					try {
						const parsedJson = JSON.parse(event.data);
						message = parsedJson?.detail ?? message;
					} catch {
						// Leave the raw payload as-is when it is not JSON.
					}
					throw new Error(message);
				}

				processText(event.data);
				scrollToBottom();
			}
		}

		buffer += decoder.decode();
		const parsed = parseSSEChunk(buffer);
		for (const event of parsed.events) {
			if (event.event !== 'done' && event.data !== '[DONE]') {
				processText(event.data);
			}
		}

		if (assistantFinalAnswer.trim().length > 0) {
			if (!currentMarkdownContainer) {
				currentMarkdownContainer = document.createElement('div');
				currentMarkdownContainer.className = 'markdown-body';
				answerContainer.appendChild(currentMarkdownContainer);
			}

			currentMarkdownContainer.innerHTML = typeof marked !== 'undefined' ? marked.parse(assistantFinalAnswer) : assistantFinalAnswer;
		}

		imageFilenames = [...new Set(retrievedResults.map((result) => result.image_filename).filter(Boolean))];
		if (imageFilenames.length > 0) {
			answerContainer.appendChild(createReferenceImages(imageFilenames));
		}

		session.messages.push({
			role: 'assistant',
			content: assistantFinalAnswer.trim(),
			thinkContent: assistantThinkText.trim() || undefined,
			imageFilenames,
		});
		updateSessionTimestamp(session);
		persistSessions();
		renderSessionList();
		scrollToBottom();
	} catch (error) {
		assistantBubble.remove();
		appendMessage('system', error instanceof Error ? error.message : 'Request failed.');
		throw error;
	} finally {
		sendButton.disabled = false;
		queryInput.disabled = false;
		queryInput.value = '';
		autoResizeTextarea();
		queryInput.focus();
	}

	return { userBubble, assistantBubble };
}

chatForm.addEventListener('submit', async (event) => {
	event.preventDefault();

	const query = queryInput.value.trim();
	if (!query) {
		return;
	}

	sendButton.disabled = true;
	queryInput.disabled = true;

	try {
		await sendMessage(query);
	} catch {
		// sendMessage already surfaces a readable system message.
	}
});

queryInput.addEventListener('input', autoResizeTextarea);
queryInput.addEventListener('keydown', (event) => {
	if (event.key === 'Enter' && !event.shiftKey) {
		event.preventDefault();
		chatForm.requestSubmit();
	}
});

sidebarToggle.addEventListener('click', openSidebar);
sidebarBackdrop.addEventListener('click', closeSidebar);
newSessionButton.addEventListener('click', createNewSession);

loadStoredSessions();
ensureSessionState();
renderSessionList();
renderSessionMessages(getActiveSession());

autoResizeTextarea();
scrollToBottom();
