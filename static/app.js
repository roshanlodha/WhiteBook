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

const THINK_LABEL = 'thinking...';

const sourceViewerState = {
	images: [],
	index: 0,
	modal: null,
	imageElement: null,
	captionElement: null,
	counterElement: null,
	previousButton: null,
	nextButton: null,
};

if (typeof marked !== 'undefined') {
	marked.setOptions({ gfm: true, breaks: true });
}

function loadStoredSessions() {
	try {
		const storedSessions = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
		if (Array.isArray(storedSessions) && storedSessions.length > 0) {
			appState.sessions = storedSessions;
			for (const session of appState.sessions) {
				if ((!session.title || session.title === 'New session' || session.title === 'New chat') && session.messages.length > 0) {
					session.title = getSessionTitle(session);
				}
			}
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

function createSession(title = 'New chat') {
	const now = Date.now();
	return {
		id: crypto.randomUUID(),
		title,
		createdAt: now,
		updatedAt: now,
		messages: [],
	};
}

function getSessionTitle(session) {
	if (session.title && session.title !== 'New session' && session.title !== 'New chat') {
		return session.title;
	}

	const firstUserMessage = session.messages.find((message) => message.role === 'user' && message.content.trim().length > 0);
	if (firstUserMessage) {
		const trimmed = firstUserMessage.content.trim();
		return trimmed.length > 42 ? `${trimmed.slice(0, 42).trim()}…` : trimmed;
	}

	return 'New chat';
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
	if (session.messages.filter((message) => message.role === 'user').length === 1) {
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

function ensureSourceViewer() {
	if (sourceViewerState.modal) {
		return;
	}

	const modal = document.createElement('div');
	modal.className = 'source-modal';
	modal.hidden = true;
	modal.setAttribute('role', 'dialog');
	modal.setAttribute('aria-modal', 'true');
	modal.setAttribute('aria-label', 'Retrieved Page');

	const backdrop = document.createElement('button');
	backdrop.type = 'button';
	backdrop.className = 'source-modal-backdrop';
	backdrop.setAttribute('aria-label', 'Close source viewer');
	backdrop.addEventListener('click', closeSourceViewer);

	const dialog = document.createElement('div');
	dialog.className = 'source-modal-dialog';

	const header = document.createElement('div');
	header.className = 'source-modal-header';

	const titleBlock = document.createElement('div');
	titleBlock.className = 'source-modal-titleblock';

	const title = document.createElement('h3');
	title.textContent = 'Retrieved Page';
	titleBlock.appendChild(title);

	const counter = document.createElement('p');
	counter.className = 'source-modal-counter';
	titleBlock.appendChild(counter);

	header.appendChild(titleBlock);

	const closeButton = document.createElement('button');
	closeButton.type = 'button';
	closeButton.className = 'source-modal-close';
	closeButton.textContent = 'Close';
	closeButton.addEventListener('click', closeSourceViewer);
	header.appendChild(closeButton);

	const frame = document.createElement('div');
	frame.className = 'source-modal-frame';

	const previousButton = document.createElement('button');
	previousButton.type = 'button';
	previousButton.className = 'source-modal-nav source-modal-prev';
	previousButton.textContent = '‹';
	previousButton.setAttribute('aria-label', 'Previous retrieved page');
	previousButton.addEventListener('click', () => moveSourceViewer(-1));

	const nextButton = document.createElement('button');
	nextButton.type = 'button';
	nextButton.className = 'source-modal-nav source-modal-next';
	nextButton.textContent = '›';
	nextButton.setAttribute('aria-label', 'Next retrieved page');
	nextButton.addEventListener('click', () => moveSourceViewer(1));

	const image = document.createElement('img');
	image.className = 'source-modal-image';
	image.alt = 'Retrieved Page';

	frame.appendChild(previousButton);
	frame.appendChild(image);
	frame.appendChild(nextButton);

	const footer = document.createElement('div');
	footer.className = 'source-modal-footer';

	const caption = document.createElement('p');
	caption.className = 'source-modal-caption';
	footer.appendChild(caption);

	dialog.appendChild(header);
	dialog.appendChild(frame);
	dialog.appendChild(footer);

	modal.appendChild(backdrop);
	modal.appendChild(dialog);
	document.body.appendChild(modal);

	sourceViewerState.modal = modal;
	sourceViewerState.imageElement = image;
	sourceViewerState.captionElement = caption;
	sourceViewerState.counterElement = counter;
	sourceViewerState.previousButton = previousButton;
	sourceViewerState.nextButton = nextButton;

	document.addEventListener('keydown', (event) => {
		if (!sourceViewerState.modal || sourceViewerState.modal.hidden) {
			return;
		}

		if (event.key === 'Escape') {
			closeSourceViewer();
		}

		if (event.key === 'ArrowLeft') {
			moveSourceViewer(-1);
		}

		if (event.key === 'ArrowRight') {
			moveSourceViewer(1);
		}
	});
}

function sourceImageUrl(imageFilename) {
	return `/static/images/${encodeURIComponent(imageFilename)}`;
}

function updateSourceViewer() {
	if (!sourceViewerState.modal || sourceViewerState.images.length === 0) {
		return;
	}

	const currentImage = sourceViewerState.images[sourceViewerState.index];
	sourceViewerState.imageElement.src = sourceImageUrl(currentImage);
	sourceViewerState.imageElement.alt = 'Retrieved Page';
	sourceViewerState.captionElement.textContent = `Page ${sourceViewerState.index + 1} of ${sourceViewerState.images.length}`;
	sourceViewerState.counterElement.textContent = `${sourceViewerState.index + 1} / ${sourceViewerState.images.length}`;
	sourceViewerState.previousButton.disabled = sourceViewerState.images.length <= 1;
	sourceViewerState.nextButton.disabled = sourceViewerState.images.length <= 1;
	if (sourceViewerState.images.length > 1) {
		sourceViewerState.previousButton.disabled = sourceViewerState.index === 0;
		sourceViewerState.nextButton.disabled = sourceViewerState.index === sourceViewerState.images.length - 1;
	}
}

function openSourceViewer(imageFilenames, startIndex = 0) {
	ensureSourceViewer();
	const normalizedImages = imageFilenames.filter(Boolean);
	if (normalizedImages.length === 0) {
		return;
	}

	sourceViewerState.images = normalizedImages;
	sourceViewerState.index = Math.min(Math.max(startIndex, 0), normalizedImages.length - 1);
	updateSourceViewer();
	sourceViewerState.modal.hidden = false;
}

function closeSourceViewer() {
	if (!sourceViewerState.modal) {
		return;
	}

	sourceViewerState.modal.hidden = true;
	sourceViewerState.images = [];
	sourceViewerState.index = 0;
}

function moveSourceViewer(delta) {
	if (sourceViewerState.images.length === 0) {
		return;
	}

	const nextIndex = sourceViewerState.index + delta;
	if (nextIndex < 0 || nextIndex >= sourceViewerState.images.length) {
		return;
	}

	sourceViewerState.index = nextIndex;
	updateSourceViewer();
}

function splitThinkParagraphs(text) {
	return text
		.split(/\n\s*\n/)
		.map((paragraph) => paragraph.trim())
		.filter(Boolean);
}

function createThinkParagraphElement(paragraphText, isOpen = false) {
	const details = document.createElement('details');
	details.className = 'think-paragraph';
	details.open = isOpen;

	const summary = document.createElement('summary');
	summary.className = 'think-summary';
	const arrow = document.createElement('span');
	arrow.className = 'think-summary-arrow';
	arrow.textContent = '>';
	const label = document.createElement('span');
	label.className = 'think-summary-label';
	label.textContent = THINK_LABEL;
	summary.appendChild(arrow);
	summary.appendChild(label);
	const syncSummary = () => {
		arrow.textContent = details.open ? '⌄' : '>';
	};
	syncSummary();
	details.addEventListener('toggle', syncSummary);
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

	thread.appendChild(createThinkParagraphElement(paragraphs.join('\n\n'), false));

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

	if (message.thinkContent) {
		const thinkContainer = document.createElement('div');
		thinkContainer.className = 'think-thread';
		updateThinkThread(thinkContainer, message.thinkContent, true);
		assistantBubble.appendChild(thinkContainer);
	}

	const answerContainer = document.createElement('div');
	answerContainer.className = 'assistant-answer';
	answerContainer.appendChild(createMarkdownContainer(message.content || ''));
	assistantBubble.appendChild(answerContainer);

	if (Array.isArray(options.imageFilenames) && options.imageFilenames.length > 0) {
		assistantBubble.appendChild(createSourceLauncher(options.imageFilenames));
	}

	chatHistory.appendChild(assistantBubble);
	scrollToBottom();
	return assistantBubble;
}

function createSourceLauncher(imageFilenames) {
	const launcher = document.createElement('div');
	launcher.className = 'source-launcher';

	const label = document.createElement('p');
	label.className = 'source-launcher-label';
	label.textContent = 'Retrieved Page';
	launcher.appendChild(label);

	const button = document.createElement('button');
	button.type = 'button';
	button.className = 'source-launcher-button';
	button.textContent = 'view source';
	button.addEventListener('click', () => openSourceViewer(imageFilenames));
	launcher.appendChild(button);

	return launcher;
}

function renderSessionList() {
	sessionList.innerHTML = '';
	const orderedSessions = [...appState.sessions].sort((left, right) => right.updatedAt - left.updatedAt);

	for (const session of orderedSessions) {
		const item = document.createElement('div');
		item.className = `session-item ${session.id === appState.activeSessionId ? 'active' : ''}`;
		item.setAttribute('role', 'listitem');

		const button = document.createElement('button');
		button.type = 'button';
		button.className = 'session-item-button';

		const title = document.createElement('span');
		title.className = 'session-title';
		title.textContent = getSessionTitle(session);
		button.appendChild(title);

		button.addEventListener('click', () => switchSession(session.id));
		item.appendChild(button);

		const deleteButton = document.createElement('button');
		deleteButton.type = 'button';
		deleteButton.className = 'session-delete-button';
		deleteButton.setAttribute('aria-label', `Delete ${getSessionTitle(session)}`);
		deleteButton.textContent = '×';
		deleteButton.addEventListener('click', (event) => {
			event.stopPropagation();
			deleteSession(session.id);
		});
		item.appendChild(deleteButton);

		sessionList.appendChild(item);
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
		const emptyState = document.createElement('section');
		emptyState.className = 'empty-chat';

		const title = document.createElement('h2');
		title.textContent = 'New chat';
		emptyState.appendChild(title);

		const body = document.createElement('p');
		body.textContent = 'Ask a question to start the conversation.';
		emptyState.appendChild(body);

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

function deleteSession(sessionId) {
	const sessionIndex = appState.sessions.findIndex((session) => session.id === sessionId);
	if (sessionIndex === -1) {
		return;
	}

	const wasActive = appState.activeSessionId === sessionId;
	appState.sessions.splice(sessionIndex, 1);

	if (appState.sessions.length === 0) {
		createNewSession();
		return;
	}

	if (wasActive) {
		appState.activeSessionId = appState.sessions[0].id;
	}

	persistSessions();
	renderSessionList();
	renderSessionMessages(getActiveSession());
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
	const thinkContainer = document.createElement('div');
	thinkContainer.className = 'think-thread';
	assistantBubble.appendChild(thinkContainer);
	const answerContainer = document.createElement('div');
	answerContainer.className = 'assistant-answer';
	assistantBubble.appendChild(answerContainer);
	const sourceContainer = document.createElement('div');
	sourceContainer.className = 'source-launcher';
	sourceContainer.hidden = true;
	assistantBubble.appendChild(sourceContainer);
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
				currentThinkContainer = thinkContainer;
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
			sourceContainer.appendChild(createSourceLauncher(imageFilenames));
			sourceContainer.hidden = false;
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
