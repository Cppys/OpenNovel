# 番茄小说作家后台 API 接口文档

> 逆向于 2026-02-23，从 fanqienovel.com 作家后台 JS bundle 抓取

## 通用信息

- **Base URL**: `https://fanqienovel.com`
- **Content-Type**: `application/x-www-form-urlencoded;charset=UTF-8`（关键！不是 JSON）
- **通用查询参数**: `aid=2503&app_name=muye_novel`
- **认证**: 依赖 Cookie（`passport_csrf_token`, `csrf_session_id` 等）

---

## 核心接口

### 1. 创建新书

**URL**: `POST /api/author/book/create/v0/?aid=2503&app_name=muye_novel`

**Content-Type**: `application/x-www-form-urlencoded`

**参数**（待确认完整字段）:
- `book_name` - 书名
- `gender` - 目标读者 (0=女频, 1=男频)
- `abstract` - 简介 (>=50字)
- `category_id` - 分类ID
- `protagonist_name_1` - 主角名1
- `protagonist_name_2` - 主角名2

**获取分类列表**: `GET /api/author/book/category_list/v0/?aid=2503&app_name=muye_novel&gender=0`

**响应示例**:
```json
{"code": 0, "data": {...}, "message": "success"}
{"code": -2, "data": null, "message": "参数有误"}
```

---

### 2. 保存草稿（自动保存 / 存草稿）

**URL**: `POST /api/author/article/cover_article/v0/`

**Content-Type**: `application/x-www-form-urlencoded;charset=UTF-8`

**参数**:
- `aid=2503`
- `app_name=muye_novel`
- `book_id` - 书籍ID（如 `7609722228128615486`）
- `item_id` - 章节ID（如 `7609730894361788990`，新章节可能由服务端生成）
- `title` - 章节标题（格式: `第 X 章 标题`）
- `content` - 正文内容（**HTML格式**，用 `<p>` 标签包裹）
- `volume_name` - 卷名（如 `第一卷：默认`）
- `volume_id` - 卷ID（如 `7609722230573911102`）

**响应**:
```json
{"code": 0, "data": {"latest_version": 1}, "message": "success"}
```

---

### 3. 发布章节

**URL**: `POST /api/author/publish_article/v0/?aid=2503&app_name=muye_novel`

**Content-Type**: `application/x-www-form-urlencoded`

**参数**: 与保存草稿类似，加上:
- `book_id`
- `volume_id`
- `volume_name`
- `title`
- `content` (HTML格式)

**注意**: 需要先通过 `cover_article` 保存草稿获取 `item_id`，再用 `publish_article` 发布

---

### 4. 修改书籍信息

**URL**: `POST /api/author/book/modify_book/v0/?aid=2503&app_name=muye_novel`

---

### 5. 获取卷列表

**URL**: `GET /api/author/volume/volume_list/v1/?aid=2503&app_name=muye_novel&book_id={book_id}`

**响应**:
```json
{
  "code": 0,
  "data": {
    "volume_list": [
      {
        "index": 1,
        "book_id": "7609722228128615486",
        "volume_id": "7609722230573911102",
        "volume_name": "第一卷：默认",
        "item_count": 5,
        "can_delete": false
      }
    ]
  }
}
```

---

### 6. 获取章节列表

**URL**: `GET /api/author/chapter/chapter_list/v1/?aid=2503&app_name=muye_novel&book_id={book_id}`

### 7. 获取草稿列表

**URL**: `GET /api/author/chapter/draft_list/v1/?aid=2503&app_name=muye_novel&book_id={book_id}`

### 8. 删除书籍

**URL**: `POST /api/author/book/delete/v0/?aid=2503&app_name=muye_novel`

### 9. 获取书籍列表（首页）

**URL**: `GET /api/author/homepage/book_list/v0/?aid=2503&app_name=muye_novel&page_count=50&page_index=0`

**注意**: 实际使用的是 `homepage/book_list`，而非 `book/book_list`（后者需要 `a_bogus` 反爬参数）

**响应**: `data.book_list` 为书籍数组，每项含 `book_id`、`book_name`、`abstract` 等字段。

### 10. 获取书籍详情

**URL**: `GET /api/author/book/book_detail/v0/?aid=2503&app_name=muye_novel&book_id={book_id}`

### 11. 保存文档历史

**URL**: `POST /api/author/article/save_doc_history/v0/`

**参数**:
- `aid=2503`
- `app_name=muye_novel`
- `book_id`
- `item_id`

---

## 完整工作流

### 发布新章节流程:
1. `GET volume_list` → 获取 volume_id
2. `POST cover_article` → 保存草稿，获取 item_id 和 version
3. `POST publish_article` → 发布章节
4. `POST save_doc_history` → 保存历史记录

### 创建新书流程:
1. `GET category_list` → 获取分类列表
2. `POST book/create` → 创建书籍
3. 获取新书的 book_id 和 volume_id

---

## 已知书籍信息

- **豪门替嫁：冷面总裁的心尖宠**: book_id=`7609722228128615486`, volume_id=`7609722230573911102`
- **韩肖天的新书**: book_id=`7609716421836147774`

---

## 完整 API 列表

从 main.js 提取的所有 `/api/author/` 端点（共 200+），关键的已在上方详细记录。

### Book 相关
- `/api/author/book/create/v0/`
- `/api/author/book/modify_book/v0/`
- `/api/author/book/delete/v0`
- `/api/author/book/book_detail/v0/`
- `/api/author/book/book_list/v0`
- `/api/author/book/category_list/v0/`
- `/api/author/book/group_category_list/v0/`

### Article/Chapter 相关
- `/api/author/article/cover_article/v0/` (保存草稿)
- `/api/author/article/new_article/v0/` (新建文章)
- `/api/author/publish_article/v0/` (发布章节)
- `/api/author/edit_article/v0/` (编辑文章)
- `/api/author/delete_article/v1` (删除文章)
- `/api/author/chapter/chapter_list/v1` (章节列表)
- `/api/author/chapter/draft_list/v1` (草稿列表)

### Volume 相关
- `/api/author/volume/volume_list/v1`
- `/api/author/volume/add_volume/v0`
- `/api/author/volume/delete_volume/v0/`
- `/api/author/volume/modify/v0`
