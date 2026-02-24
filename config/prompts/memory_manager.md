# Memory Manager Agent Prompt

## 章节摘要生成

**指令：** 请为以下章节生成结构化摘要。

**章节内容：**
{chapter_content}

请输出JSON格式：
```json
{
  "summary": "200-300字的章节摘要，涵盖：主要事件、角色行动、情感变化、新信息揭示",
  "character_updates": [
    {
      "name": "角色名",
      "changes": "本章中该角色的状态变化（情感、能力、关系、处境）",
      "new_info": "本章揭示的关于该角色的新信息"
    }
  ],
  "plot_events": [
    {
      "event_type": "foreshadow|climax|reveal|twist|setup|resolution",
      "description": "事件描述",
      "importance": "critical|major|normal|minor",
      "resolved": false
    }
  ],
  "new_characters": [
    {
      "name": "新角色名",
      "role": "protagonist|antagonist|supporting|minor",
      "description": "外貌与性格初步描述",
      "first_action": "首次登场的行为/台词"
    }
  ],
  "world_updates": [
    {
      "category": "geography|power_system|faction|culture|rules",
      "name": "设定名称",
      "description": "新揭示或变化的世界设定"
    }
  ]
}
```

## 全局回顾 Prompt

**指令：** 请对以下小说的整体进展进行全局回顾和一致性检查。

**所有章节摘要：**
{all_summaries}

**当前角色卡：**
{character_cards}

**未解决的伏笔：**
{unresolved_threads}

请输出JSON格式：
```json
{
  "story_progression": "当前故事进展到什么阶段的总结（100-200字）",
  "character_arc_updates": [
    {
      "name": "角色名",
      "current_state": "角色当前状态的综合描述",
      "development_notes": "角色发展轨迹分析"
    }
  ],
  "inconsistencies": [
    {
      "description": "发现的不一致之处",
      "chapters_involved": [1, 5],
      "severity": "critical|minor",
      "suggestion": "如何在后续章节修正"
    }
  ],
  "stale_threads": [
    {
      "description": "超过15章未推进的伏笔",
      "setup_chapter": 3,
      "suggestion": "建议在哪些章节推进或解决"
    }
  ]
}
```
