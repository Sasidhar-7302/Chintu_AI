# Chintu AI - Manual QA Matrix

Only provide these inputs to Chintu and compare the expected result.

---

## Basic Conversation
| Input | Expected Result |
|-------|-----------------|
| `hi` | Greets you using your saved name. |
| `how are you?` | Friendly response, asks how it can help. |
| `what is your status?` | System health summary. |
| `what time is it?` | Speaks current time. |

---

## Memory
| Input | Expected Result |
|-------|-----------------|
| `remember that my favorite color is blue` | Confirms saving memory. |
| `what is my favorite color?` | Replies “blue”. |
| `forget my favorite color` | Confirms deletion. |

---

## App & Window Control (Windows)
| Input | Expected Result |
|-------|-----------------|
| `open notepad` | Opens Notepad. |
| `open chrome` | Opens Chrome. |
| `close chrome` | Asks for confirmation. |
| `i confirm` | Closes Chrome. |
| `minimize window` | Chintu UI minimizes. |
| `maximize window` | Chintu UI maximizes. |
| `show window` | Chintu UI restores. |
| `what apps are open` | Lists open windows. |

---

## Web / Search
| Input | Expected Result |
|-------|-----------------|
| `open youtube` | Opens YouTube in browser. |
| `search for electric cars` | Google search opens. |
| `deep search about LLM fine-tuning techniques` | Returns detailed multi-source response. |

---

## Files
| Input | Expected Result |
|-------|-----------------|
| `list files in my Documents folder` | Lists files or asks for path. |
| `read readme.txt in my Desktop` | Reads file content or asks for correct path. |

---

## Tasks & Scheduling
| Input | Expected Result |
|-------|-----------------|
| `add task: buy groceries tomorrow at 5pm` | Task created. |
| `list my tasks` | Shows pending tasks. |
| `complete task: buy groceries` | Marks task done. |
| `every day at 9am, search for news about AI` | Scheduled workflow created. |
| `cancel scheduled task <id>` | Cancels the schedule. |

---

## Job Apply
| Input | Expected Result |
|-------|-----------------|
| `job apply this JD: <paste>` | Parses JD, proposes fit, asks for approval. |
| `list job applications` | Shows tracked applications. |
| `job apply using resume notes only` | Produces resume notes and waits for approval. |

---

## Skills (Declarative)
| Input | Expected Result |
|-------|-----------------|
| `weather in Hyderabad` | Weather response via skill. |
| `open outlook` | Opens Outlook. |
| `open calendar` | Opens Calendar or runs skill. |
| `open notion` | Opens Notion or asks for token. |

---

## A2UI (Forms / Tables)
| Input | Expected Result |
|-------|-----------------|
| `show open windows` | Renders table/card in UI. |
| `connect github` | Credential form popup. |
| (enter token in popup) | Saved via config writer, confirmation shown. |
| `set config CHINTU_JOB_APPLY_DEFAULT_LOCATION=Hyderabad` | Shows confirmation card before saving. |

---

## Media and Vision
| Input | Expected Result |
|-------|-----------------|
| `analyze image C:\\path\\to\\img.png` | Returns image summary or OCR text. |
| `summarize video C:\\path\\to\\clip.mp4` | Extracts frames and returns summary. |
| `build news video about AI today` | Builds a draft video plan and asks for approval. |

---

## Orchestrator / Long Tasks
| Input | Expected Result |
|-------|-----------------|
| `plan a 3-step research workflow on EVs` | Plan shown, approval requested. |
| `approve step` | Step runs, progress updates. |
| `cancel this workflow` | Workflow stops. |

---

## Channels (Optional)
| Input | Expected Result |
|-------|-----------------|
| `connect telegram` | Asks for bot token (popup or chat). |
| `hi` (sent on Telegram) | Chintu replies on Telegram. |
| `connect whatsapp` | Starts pairing flow. |

---

## Security & Sandbox
| Input | Expected Result |
|-------|-----------------|
| `delete all notes` | Requires confirmation before action. |
| `run python code in sandbox` | Uses Docker if enabled, else fallback. |

---

## Swarm / Chintu Hive (The Hive)
| Input | Expected Result |
|-------|-----------------|
| `build a python snake game` | Orchestrator plans, AutonCoder generates code. |
| `find the best noise cancelling headphones under $200` | ShoppingAgent searches and compares. |
| `remind me to call the doctor and update my goal to fix the car` | TaskMaster decomposes and adds tasks/goals. |
| `plan a trip to Tokyo` | Orchestrator delegates to web search and planners. |

