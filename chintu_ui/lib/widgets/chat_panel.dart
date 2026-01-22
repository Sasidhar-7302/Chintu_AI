import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class ChatPanel extends StatelessWidget {
  final List<Map<String, dynamic>> messages;
  final Function(String) onSendMessage;

  const ChatPanel({
    super.key,
    required this.messages,
    required this.onSendMessage,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.3),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
        boxShadow: [
          BoxShadow(
            color: Colors.cyan.withValues(alpha: 0.1),
            blurRadius: 20,
            spreadRadius: -5,
          ),
        ],
      ),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  Colors.cyan.withValues(alpha: 0.1),
                  Colors.purple.withValues(alpha: 0.1),
                ],
              ),
              borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
              border: Border(
                bottom: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
              ),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [Colors.cyan, Colors.purple],
                    ),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(Icons.chat_bubble_outline, color: Colors.white, size: 16),
                ),
                const SizedBox(width: 12),
                const Text(
                  'Conversation',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const Spacer(),
                // COPY ALL BUTTON
                IconButton(
                  icon: const Icon(Icons.copy_all, color: Colors.white70),
                  tooltip: 'Copy Full Conversation',
                  onPressed: () {
                    if (messages.isEmpty) return;
                    final text = messages.map((m) {
                      final role = m['role'] == 'user' ? 'You' : 'Chintu';
                      return "$role: ${m['text']}";
                    }).join('\n\n');
                    
                    Clipboard.setData(ClipboardData(text: text));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Full conversation copied!'),
                        duration: Duration(seconds: 1),
                        behavior: SnackBarBehavior.floating,
                        width: 250,
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
          // Messages
          Expanded(
            child: messages.isEmpty
                ? Center(
                    child: Text(
                      'Start a conversation by saying\n"Hey Chintu"',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: Colors.grey.shade500,
                        fontSize: 14,
                      ),
                    ),
                  )
                : SelectionArea( // Enables drag selection across messages
                    child: ListView.builder(
                      padding: const EdgeInsets.all(16),
                      itemCount: messages.length,
                      reverse: true,
                      itemBuilder: (context, index) {
                        final msg = messages[messages.length - 1 - index];
                        return _ChatBubble(
                          text: msg['text'] as String,
                          isUser: msg['role'] == 'user',
                        );
                      },
                    ),
                  ),
          ),
          // Input
          _ChatInput(onSend: onSendMessage),
        ],
      ),
    );
  }
}

class _ChatBubble extends StatelessWidget {
  final String text;
  final bool isUser;

  const _ChatBubble({required this.text, required this.isUser});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.7,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
          children: [
            if (isUser) ...[
               _CopyButton(text: text),
               const SizedBox(width: 4),
            ],
            Flexible(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: isUser
                        ? [Colors.cyan.withValues(alpha: 0.4), Colors.cyan.withValues(alpha: 0.2)]
                        : [Colors.purple.withValues(alpha: 0.4), Colors.purple.withValues(alpha: 0.2)],
                  ),
                  borderRadius: BorderRadius.only(
                    topLeft: const Radius.circular(16),
                    topRight: const Radius.circular(16),
                    bottomLeft: Radius.circular(isUser ? 16 : 4),
                    bottomRight: Radius.circular(isUser ? 4 : 16),
                  ),
                  border: Border.all(
                    color: (isUser ? Colors.cyan : Colors.purple).withValues(alpha: 0.3),
                  ),
                ),
                // CHANGED: SelectableText -> Text to allow SelectionArea to work properly
                child: Text(
                  text,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                ),
              ),
            ),
            if (!isUser) ...[
               const SizedBox(width: 4),
               _CopyButton(text: text),
            ],
          ],
        ),
      ),
    );
  }
}

class _CopyButton extends StatelessWidget {
  final String text;

  const _CopyButton({required this.text});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: Icon(Icons.copy, size: 14, color: Colors.white.withValues(alpha: 0.5)),
      tooltip: 'Copy Message',
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(),
      onPressed: () {
        Clipboard.setData(ClipboardData(text: text));
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Message copied!'),
            duration: const Duration(milliseconds: 1),
            behavior: SnackBarBehavior.floating,
            width: 150,
          ),
        );
      },
    );
  }
}

class _ChatInput extends StatefulWidget {
  final Function(String) onSend;

  const _ChatInput({required this.onSend});

  @override
  State<_ChatInput> createState() => _ChatInputState();
}

class _ChatInputState extends State<_ChatInput> {
  final _controller = TextEditingController();

  void _send() {
    if (_controller.text.trim().isNotEmpty) {
      widget.onSend(_controller.text.trim());
      _controller.clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            Colors.cyan.withValues(alpha: 0.05),
            Colors.purple.withValues(alpha: 0.05),
          ],
        ),
        border: Border(
          top: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Type a command...',
                hintStyle: TextStyle(color: Colors.grey.shade600),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                  borderSide: BorderSide.none,
                ),
                filled: true,
                fillColor: Colors.white.withValues(alpha: 0.1),
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              ),
              onSubmitted: (_) => _send(),
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            onPressed: _send,
            icon: const Icon(Icons.send, color: Colors.cyan),
          ),
        ],
      ),
    );
  }
}
