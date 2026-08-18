


# memory.py
# Store recent conversation history for multi-turn question answering.
# Conversation history is sent only to the LLM, not used for retrieval.
# Older conversations are removed automatically to limit memory size.
# The first topic is kept to maintain conversation context.
# Memory size is controlled by config.MEMORY_MAX_TURNS.


import config

# Convert message role to human-readable text
ROLE_NAMES = {"user": "User", "assistant": "Assistant"}


class ConversationMemory:
    def __init__(self):
        self.messages = []      # [{"role": "user", "content": "..."}, ...]
        self.first_topic = ""   # First topic discussed, kept to stay on point

    def add_user(self, text):
        self.add("user", text)

    def add_assistant(self, text):
        self.add("assistant", text)

    def add(self, role, text):
        self.messages.append({"role": role, "content": text})
        self.forget_old_messages()

    def forget_old_messages(self):
        """Remove old messages when exceeding quota (1 turn = user asks + assistant answers = 2 messages)"""
        limit = config.MEMORY_MAX_TURNS * 2

        while len(self.messages) > limit:
            removed = self.messages.pop(0)

            # Remember the first topic before it gets removed
            if not self.first_topic and removed["role"] == "user":
                self.first_topic = removed["content"][:100]

    def get_context(self):  # Return all history as text for the prompt
        lines = []

        if self.first_topic:
            lines.append(f"[Previous topic: {self.first_topic}]")

        for message in self.messages:
            name = ROLE_NAMES.get(message["role"], message["role"])
            lines.append(f"{name}: {message['content']}")

        return "\n".join(lines)


# Determine whether the query depends on previous conversation context.
# Short follow-up questions usually require conversation history.
# Used to decide whether query rewriting is needed.
# Example: "What are the side effects?" → True
# Example: "What is PrEP?" → False


    def is_followup(self, query):
        if not self.messages:
            return False

        markers = ("and", "it", "that", "this", "next", "more", "why", "then")
        text = query.strip()
        return len(text) < 30 and text.startswith(markers)

    def clear(self):
        self.messages = []
        self.first_topic = ""


