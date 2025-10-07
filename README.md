async def run_in_executor(func, *args, **kwargs):
    """Hàm helper để chạy một hàm đồng bộ trong thread pool."""
    if jira_pat is None:
        raise HTTPException(status_code=503, detail="Jira connection not available.")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

def _format_story_data(story_issue: Dict[str, Any]) -> Dict[str, Any]:
    """Chuyển đổi một Jira issue object thành một dictionary story chuẩn."""
    fields = story_issue.get('fields', {})
    assignee = fields.get('assignee')
    status = fields.get('status')
    return {
        "key": story_issue.get('key'), "summary": fields.get('summary'),
        "status": status.get('name') if status else None,
        "assignee": assignee.get('displayName') if assignee else None,
        "story_points": fields.get(CONFIG["jira_fields"]["story_points"], 0) or 0,
        "created": fields.get('created'), "updated": fields.get('updated'),
    }

def _analyze_epic_issues(stories: List[Dict[str, Any]], deviation: float) -> Tuple[List[str], List[str]]:
    """Phân tích danh sách story để tìm ra nguyên nhân gốc rễ và đề xuất hành động."""
    root_causes, path_to_green = [], []
    now, threshold_days = datetime.now(timezone.utc), CONFIG['analysis_thresholds']['in_progress_too_long_days']
    
    # Logic phân tích giữ nguyên vì nó là CPU-bound
    blocked = [s['key'] for s in stories if s['status'] and s['status'].upper() in ['BLOCKED', 'IMPEDIMENT']]
    unassigned = [s['key'] for s in stories if not s['assignee'] and s['status'] and s['status'].upper() not in ['DONE', 'CLOSED']]
    in_progress_too_long, workload = [], {}

    for story in stories:
        if story['status'] and story['status'].upper() not in ['DONE', 'CLOSED']:
            if story['assignee']: workload.setdefault(story['assignee'], []).append(story['key'])
            if story['status'].upper() == 'IN PROGRESS' and story.get('updated'):
                try:
                    updated_date = datetime.fromisoformat(story['updated'].replace('Z', '+00:00'))
                    if (now - updated_date).days > threshold_days: in_progress_too_long.append(story['key'])
                except (ValueError, TypeError): pass

    overloaded = {a: s for a, s in workload.items() if len(s) > CONFIG['analysis_thresholds']['overloaded_assignee_stories']}
    
    if blocked:
        keys = ", ".join(blocked[:3])
        root_causes.append(f"{len(blocked)} story đang bị block ({keys},...).")
        path_to_green.append(f"Ưu tiên giải quyết các story bị block: {keys}.")

    if in_progress_too_long:
        keys = ", ".join(in_progress_too_long[:3])
        root_causes.append(f"{len(in_progress_too_long)} story đã 'In Progress' quá {threshold_days} ngày ({keys},...).")
        path_to_green.append(f"Kiểm tra và hỗ trợ các story đang tiến triển chậm: {keys}.")
    
    # ... (thêm các phân tích khác nếu cần)
    return root_causes, path_to_green


# --- API ENDPOINTS (PHIÊN BẢN ASYNC) ---

@router.get("/jira/stories/{story_key}/details", summary="Get Detailed User Story (Async)")
async def get_detail_user_story_jira(story_key: str = Path(..., description="Story Key")):
    """(Tool) Lấy thông tin chi tiết của một user story."""
    try:
        story_issue = await run_in_executor(jira_pat.issue, story_key)
        return _format_story_data(story_issue.raw)
    except JIRAError as e:
        if e.status_code == 404: raise HTTPException(status_code=404, detail=f"Story '{story_key}' not found.")
        raise HTTPException(status_code=500, detail=f"Jira API error: {e.text}")

@router.get("/jira/epics/{epic_key}/progress", summary="Calculate Epic Progress (Async)")
async def calculate_epic_progress(epic_key: str = Path(..., description="Epic Key")):
    """(Tool) Phân tích tiến độ và sức khỏe của epic một cách toàn diện."""
    try:
        # Tối ưu: Chạy song song 2 cuộc gọi API độc lập
        story_jql = f'"Epic Link" = {epic_key} AND issuetype = Story'
        epic_task = run_in_executor(jira_pat.issue, epic_key)
        stories_task = run_in_executor(jira_pat.search_issues, story_jql, maxResults=1000)
        epic_issue, stories_result = await asyncio.gather(epic_task, stories_task)
        
        stories = [_format_story_data(s.raw) for s in stories_result]

        # Logic tính toán (CPU-bound) giữ nguyên
        plan_progress = 0.0
        target_start = epic_issue.fields.__dict__.get(CONFIG["jira_fields"]["epic_target_start"])
        target_end = epic_issue.fields.__dict__.get(CONFIG["jira_fields"]["epic_target_end"])
        if target_start and target_end:
            try:
                s, e, c = datetime.strptime(target_start, '%Y-%m-%d'), datetime.strptime(target_end, '%Y-%m-%d'), datetime.now()
                total_days, elapsed_days = (e - s).days, (c - s).days
                if total_days > 0: plan_progress = min(100, max(0, (elapsed_days / total_days) * 100))
            except (ValueError, TypeError): pass

        total_points = sum(s['story_points'] for s in stories)
        if total_points > 0:
            weighted_progress = sum(s['story_points'] * CONFIG['status_mapping'].get(s['status'].upper() if s['status'] else "", {}).get('min_progress', 0) for s in stories)
            actual_progress = weighted_progress / (total_points * 100) if total_points else 0
        else:
            done = sum(1 for s in stories if s['status'] and s['status'].upper() in ['DONE', 'CLOSED', 'RELEASED', 'PROD'])
            actual_progress = (done / len(stories)) * 100 if stories else 0

        deviation = actual_progress - plan_progress
        rag, msg = "BLUE", "Không đủ dữ liệu."
        if target_start and target_end:
            if deviation > CONFIG['analysis_thresholds']['rag_deviation']['amber_gt']: rag, msg = "GREEN", "Dự án đang đi đúng tiến độ hoặc vượt kế hoạch."
            elif deviation > CONFIG['analysis_thresholds']['rag_deviation']['amber_lt']: rag, msg = "AMBER", "Dự án có dấu hiệu chậm tiến độ, cần theo dõi."
            else: rag, msg = "RED", "Dự án đang chậm tiến độ nghiêm trọng, cần can thiệp."
        
        causes, green_path = _analyze_epic_issues(stories, deviation)

        return {
            "epic_key": epic_key, "epic_summary": epic_issue.fields.summary,
            "target_start": target_start, "target_end": target_end,
            "plan_progress_percentage": round(plan_progress, 2),
            "actual_progress_percentage": round(actual_progress, 2),
            "deviation_percentage": round(deviation, 2),
            "rag_status": rag, "rag_message": msg,
            "root_causes": causes or ["Chưa phát hiện rủi ro rõ ràng."],
            "path_to_green": green_path or ["Tiếp tục theo dõi tiến độ."]
        }
    except JIRAError as e:
        if e.status_code == 404: raise HTTPException(status_code=404, detail=f"Epic '{epic_key}' not found.")
        raise HTTPException(status_code=500, detail=f"Jira API error: {e.text}")

@router.get("/jira/epics/{epic_key}/overview", summary="Get Epic Overview Statistics (Async)")
async def get_jira_epic_overview(epic_key: str = Path(..., description="Epic Key")):
    """(Tool) Lấy thông tin tổng quan và thống kê chi tiết của epic."""
    try:
        # Tối ưu: Chạy song song 2 cuộc gọi API độc lập đầu tiên
        story_jql = f'"Epic Link" = {epic_key} AND issuetype = Story'
        epic_task = run_in_executor(jira_pat.issue, epic_key, expand="renderedFields")
        stories_task = run_in_executor(jira_pat.search_issues, story_jql, maxResults=1000)
        epic_issue, stories_result = await asyncio.gather(epic_task, stories_task)

        stories = [_format_story_data(s.raw) for s in stories_result]
        story_keys = [s['key'] for s in stories]

        # Cuộc gọi API thứ 3 (lấy subtask) phụ thuộc vào kết quả của cuộc gọi thứ 2
        subtasks_by_parent = {}
        if story_keys:
            subtask_jql = f'parent in ({",".join(story_keys)})'
            subtasks_result = await run_in_executor(jira_pat.search_issues, subtask_jql, maxResults=1000)
            for subtask in subtasks_result:
                parent_key = subtask.fields.parent.key
                subtasks_by_parent.setdefault(parent_key, []).append(_format_story_data(subtask.raw))

        # Thống kê (CPU-bound)
        status_breakdown, assignee_breakdown = {}, {}
        for story in stories:
            story['subtasks'] = subtasks_by_parent.get(story['key'], [])
            status = story.get('status', 'No Status')
            assignee = story.get('assignee', 'Unassigned')
            status_breakdown[status] = status_breakdown.get(status, 0) + 1
            assignee_breakdown[assignee] = assignee_breakdown.get(assignee, 0) + 1
            
        return {
            "epic_key": epic_issue.key, "epic_summary": epic_issue.fields.summary,
            "epic_status": epic_issue.fields.status.name,
            "total_stories": len(stories),
            "total_story_points": sum(s['story_points'] for s in stories),
            "status_breakdown": status_breakdown,
            "assignee_breakdown": assignee_breakdown,
            "stories": stories,
        }
    except JIRAError as e:
        if e.status_code == 404: raise HTTPException(status_code=404, detail=f"Epic '{epic_key}' not found.")
        raise HTTPException(status_code=500, detail=f"Jira API error: {e.text}")
