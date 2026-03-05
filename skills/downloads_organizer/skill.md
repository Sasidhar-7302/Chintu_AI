# downloads organizer
Description: Shows how to move PDFs from Downloads to Documents and EXEs to Installers; optional execution flag performs the move.
Triggers: organize downloads, organize my downloads folder, organize.*downloads.*pdf.*exe, write code to move all pdf files to documents and exe files to installers
Command: python {SKILL_DIR}/organize_downloads.py --request "{request}"
Args: request
Type: shell
Requires-Bin: python
