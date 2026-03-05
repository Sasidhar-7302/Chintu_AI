import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import '../theme/app_theme.dart';

class ChatPanel extends StatelessWidget {
  final List<Map<String, dynamic>> messages;
  final Function(String, {List<String>? filePaths}) onSendMessage;

  const ChatPanel({
    super.key,
    required this.messages,
    required this.onSendMessage,
  });

  @override
  Widget build(BuildContext context) {
    // Glassmorphism Container
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          // Header
          _buildHeader(context),
          
          // Messages Area
          Expanded(
            child: messages.isEmpty
                ? _buildEmptyState()
                : _buildMessageList(),
          ),
          
          // Input Area
          _ChatInput(onSend: onSendMessage),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(Icons.chat_bubble_outline, color: AppColors.accent, size: 16),
          ),
          const SizedBox(width: 12),
          Text(
            'Conversation',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(fontSize: 16),
          ),
          const Spacer(),
          // Copy Button
          IconButton(
            icon: const Icon(Icons.copy_all, size: 18),
            tooltip: 'Copy Full Conversation',
            color: AppColors.textMuted,
            onPressed: () {
              if (messages.isEmpty) return;
              final text = messages.map((m) {
                final role = m['role'] == 'user' ? 'You' : 'Chintu';
                return "$role: ${m['text']}";
              }).join('\n\n');
              
              Clipboard.setData(ClipboardData(text: text));
            },
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.auto_awesome, size: 48, color: AppColors.border),
          const SizedBox(height: 16),
          Text(
            'Start a conversation\nSay "Hey Chintu"',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textMuted,
              fontSize: 14,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageList() {
    return SelectionArea(
      child: ListView.builder(
        padding: const EdgeInsets.all(20),
        itemCount: messages.length,
        reverse: true,
        itemBuilder: (context, index) {
          final msg = messages[messages.length - 1 - index];
          final isUser = msg['role'] == 'user';
          // Check for new message grouping here in future
          return _ChatBubble(
            text: msg['text'] as String,
            isUser: isUser,
          );
        },
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
        margin: const EdgeInsets.only(bottom: 12),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.75,
        ),
        child: Column(
          crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (!isUser) ...[
                  // Avatar or Icon for Chintu
                  Container(
                    width: 28, 
                    height: 28,
                    margin: const EdgeInsets.only(right: 8, bottom: 4),
                    decoration: BoxDecoration(
                      color: AppColors.surfaceElevated,
                      shape: BoxShape.circle,
                      border: Border.all(color: AppColors.border),
                    ),
                    child: const Icon(Icons.smart_toy, size: 14, color: AppColors.accent),
                  ),
                ],
                
                Flexible(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    decoration: BoxDecoration(
                      color: isUser 
                          ? AppColors.accent.withValues(alpha: 0.15)
                          : AppColors.surfaceElevated,
                      border: Border.all(
                        color: isUser 
                            ? AppColors.accent.withValues(alpha: 0.3)
                            : AppColors.border,
                      ),
                      borderRadius: BorderRadius.only(
                        topLeft: const Radius.circular(16),
                        topRight: const Radius.circular(16),
                        bottomLeft: Radius.circular(isUser ? 16 : 4),
                        bottomRight: Radius.circular(isUser ? 4 : 16),
                      ),
                    ),
                    child: Text(
                      text,
                      style: TextStyle(
                        color: isUser ? AppColors.textPrimary : AppColors.textPrimary,
                        fontSize: 14,
                        height: 1.4,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ChatInput extends StatefulWidget {
  final Function(String, {List<String>? filePaths}) onSend;

  const _ChatInput({required this.onSend});

  @override
  State<_ChatInput> createState() => _ChatInputState();
}

class _ChatInputState extends State<_ChatInput> {
  final _controller = TextEditingController();
  final FocusNode _focusNode = FocusNode();
  final List<PlatformFile> _selectedFiles = [];
  bool _isComposing = false;

  void _send() {
    final text = _controller.text.trim();
    if (text.isNotEmpty || _selectedFiles.isNotEmpty) {
      widget.onSend(
        text, 
        filePaths: _selectedFiles.map((f) => f.path!).toList()
      );
      
      _controller.clear();
      setState(() {
        _selectedFiles.clear();
        _isComposing = false;
      });
      _focusNode.requestFocus(); // Keep focus
    }
  }

  Future<void> _pickFiles() async {
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        allowMultiple: true,
        type: FileType.any,
      );

      if (result != null) {
        setState(() {
          _selectedFiles.addAll(result.files);
        });
      }
    } catch (e) {
      debugPrint('File picker error: $e');
    }
  }

  void _removeFile(PlatformFile file) {
    setState(() {
      _selectedFiles.remove(file);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        color: AppColors.surface, // Slightly darker input area
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // File Preview Area
          if (_selectedFiles.isNotEmpty)
            Container(
              height: 50,
              margin: const EdgeInsets.only(bottom: 12),
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                itemCount: _selectedFiles.length,
                itemBuilder: (context, index) {
                  final file = _selectedFiles[index];
                  return Container(
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.fromLTRB(12, 0, 8, 0),
                    decoration: BoxDecoration(
                      color: AppColors.surfaceElevated,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppColors.border),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.attach_file, size: 14, color: AppColors.accent),
                        const SizedBox(width: 8),
                        ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 150),
                          child: Text(
                            file.name,
                            style: const TextStyle(fontSize: 12),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        const SizedBox(width: 4),
                        IconButton(
                          icon: const Icon(Icons.close, size: 14, color: AppColors.textMuted),
                          onPressed: () => _removeFile(file),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(),
                          splashRadius: 16,
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
            
          // Input Row
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              // Attachment Button
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: IconButton(
                  onPressed: _pickFiles,
                  icon: const Icon(Icons.attach_file),
                  color: _selectedFiles.isNotEmpty ? AppColors.accent : AppColors.textMuted,
                  tooltip: 'Attach file',
                  style: IconButton.styleFrom(
                    backgroundColor: AppColors.surfaceElevated,
                    padding: const EdgeInsets.all(12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              
              // Text Field
              Expanded(
                child: Container(
                  decoration: BoxDecoration(
                    color: AppColors.surfaceElevated,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                      color: _isComposing ? AppColors.border : Colors.transparent, 
                    ),
                  ),
                  child: TextField(
                    controller: _controller,
                    focusNode: _focusNode,
                    minLines: 1,
                    maxLines: 5,
                    style: const TextStyle(color: AppColors.textPrimary, height: 1.4),
                    cursorColor: AppColors.accent,
                    
                    decoration: const InputDecoration(
                      hintText: 'Type a message...',
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                      filled: false, 
                    ),
                    onChanged: (text) {
                      setState(() {
                         _isComposing = text.trim().isNotEmpty;
                      });
                    },
                    onSubmitted: (text) {
                      // Prevent submit on shift+enter (Handled by TextField usually, but ensuring)
                      _send();
                    },
                    textInputAction: TextInputAction.send,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              
              // Send Button
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: IconButton(
                  onPressed: _isComposing || _selectedFiles.isNotEmpty ? _send : null,
                  icon: const Icon(Icons.arrow_upward_rounded, size: 20),
                  color: AppColors.background,
                  style: IconButton.styleFrom(
                     backgroundColor: (_isComposing || _selectedFiles.isNotEmpty) 
                        ? AppColors.accent 
                        : AppColors.surfaceElevated,
                     disabledBackgroundColor: AppColors.surfaceElevated,
                     disabledForegroundColor: AppColors.textMuted.withValues(alpha: 0.3),
                     padding: const EdgeInsets.all(12),
                     shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)), 
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
