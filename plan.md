### **Phase 4: Qwen3 Local Inference Engine**
> "Integrate the generative AI engine.
> 
> **Setup:**
> 1. Add the latest version of `llama.cpp` to the project via SPM. 
> 2. Assume we have added `Qwen3-4B-Instruct-Q4_K_M.gguf` to the bundle.
> 
> **Inference Wrapper (`LLMService.swift`):**
> 1. Write an `LLMService` class that initializes the context with `GGML_USE_METAL` enabled for GPU acceleration.
> 2. Write a function `generate(query: String, context: [Chunk]) -> AsyncStream<String>`. 
> 3. The system prompt must be: 'You are an emergency medicine assistant. Answer strictly using the provided context chunks. If the context relies on a visual diagram, explicitly state the user should reference the attached image.'
> 4. Ensure the prompt generation respects the Qwen3 chat template, specifically setting up the inference to yield the `<think>` reasoning tokens as well as the final output."

### **Phase 5: The Interface & Visual Routing**
> "Design the main SwiftUI interface. The design system must be strictly 'minimalist maximalism'—high data density, stark geometry, and zero visual clutter.
> 
> **Styling:**
> 1. Use pure black or white backgrounds with heavy reliance on Apple's SF Pro font weights to establish hierarchy.
> 2. Use pastel orange strictly as the primary accent color for active states, user bubbles, and highlighting the model's `<think>` reasoning block.
> 
> **Views (`ChatView.swift` & `ContextCard.swift`):**
> 1. Create a `ChatView` that handles the streaming `AsyncStream` response. It must actively parse the incoming text: anything between `<think>` and `</think>` should be styled in italicized pastel orange to represent the model's clinical reasoning process, while the final answer renders in standard text.
> 2. Implement a `ContextCard` view below the chat output to display the retrieved chunks. If a chunk has an `image_filename`, dynamically load and render that exact PNG from the bundle inline. The image must be wrapped in a `MagnificationGesture` for pinch-to-zoom capabilities. Provide the complete SwiftUI code."

### **Phase 6: Multi-Turn Conversation State & Chat History**

"We are upgrading the 'staffbook' iOS app to support multi-turn chatbot conversations. Act as a Lead iOS Developer.

Step 1: State Management Models

Create a ChatMessage struct conforming to Identifiable and Codable. It must include: id (UUID), role (enum: .system, .user, .assistant), content (String), and attachedImages (an array of filenames, optional).

In our existing ChatViewModel, replace the single query state with a published array @Published var messages: [ChatMessage] = [].

Step 2: Updating the LLM Service (LLMService.swift)

Modify the generateResponse function signature to accept the full conversation history: func generateResponse(history: [ChatMessage], newContext: [Chunk]) -> AsyncStream<String>.

Prompt Construction Logic: You must format the llama.cpp input strictly using the Qwen3 ChatML template format.
a. Begin with the System Message: 'You are an elite emergency medicine resident. Answer using the provided context. If the answer is not in the context, say you do not know.'
b. Append the dynamic context explicitly to the system block or the latest user message: '--- NEW RETRIEVED CONTEXT --- [Insert Chunks]'.
c. Loop through the history array and append them in the exact ChatML format (<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant...).

Ensure the context window (n_ctx) initialized in llama.cpp is set to at least 4096 or 8192 so it doesn't crash when the conversation history grows.

Step 3: Updating the UI (ChatView.swift)

Refactor the ChatView to iterate through the messages array.

Maintain the 'minimalist maximalism' aesthetic.

User messages should be aligned right, utilizing a pastel orange background (Color(hex: "#FFB347")) with stark black or white text depending on dark mode.

Assistant messages should be aligned left, using a subtle gray/off-black background.

If the Assistant's message contains <think> blocks, ensure that specific text is parsed and rendered in italicized pastel orange, while the rest of the answer remains standard text.

Ensure the ScrollView automatically pins to the bottom whenever a new token is yielded from the AsyncStream.

Provide the complete, refactored Swift code for ChatViewModel, LLMService, and ChatView."

By formatting the prompt this way, the local Qwen3 model will "read" the entire chat log, process the newly retrieved clinical chunks, and output a highly contextualized answer.