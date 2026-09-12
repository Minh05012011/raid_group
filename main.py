#!/usr/bin/env python3
import asyncio
import sys
import os
import json
import time
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(HERE, 'src')):
    SRC_DIR = os.path.join(HERE, 'src')
else:
    SRC_DIR = os.path.dirname(HERE)
sys.path.insert(0, SRC_DIR)
print(f"📂 SRC_DIR = {SRC_DIR}")

from _core._session import dataGetHome
from _core._utils import formAll, mainRequests, send_request_async, gen_threading_id
from _messaging._send import api as SendAPI

COOKIE_FILE = "cookie.txt"
MESS_FILE = "mess.txt"
LOGIN_TIMEOUT = 30

async def create_group(data_fb, user_ids, first_message="Hello"):
    fb_id = str(data_fb["FacebookID"])
    if isinstance(user_ids, (str, int)):
        user_ids = [str(user_ids)]

    dataForm = formAll(data_fb, requireGraphql=False)
    rand_id = gen_threading_id()
    now_ms = int(time.time() * 1000)

    dataForm.update({
        "client": "mercury",
        "action_type": "ma-type:user-generated-message",
        "author": f"fbid:{fb_id}",
        "body": first_message,
        "timestamp": now_ms,
        "timestamp_absolute": "Today",
        "source": "source:chat:web",
        "source_tags[0]": "source:chat",
        "client_thread_id": f"root:{rand_id}",
        "offline_threading_id": rand_id,
        "message_id": rand_id,
        "threading_id": f"<{now_ms}:{random.randrange(2**32)}-{random.randrange(2**31):x}@mail.projektitan.com>",
        "ephemeral_ttl_mode": "0",
        "ui_push_phase": "V3"
    })
    for prop in ["is_unread", "is_cleared", "is_forward", "is_filtered_content",
                 "is_filtered_content_bh", "is_filtered_content_account",
                 "is_filtered_content_quasar", "is_filtered_content_invalid_app",
                 "is_spoof_warning"]:
        dataForm[prop] = False

    for i, uid in enumerate(user_ids):
        clean_uid = str(uid).replace("fbid:", "").strip()
        if clean_uid and clean_uid != fb_id:
            dataForm[f"specific_to_list[{i}]"] = f"fbid:{clean_uid}"
    dataForm[f"specific_to_list[{len(user_ids)}]"] = f"fbid:{fb_id}"

    url = "https://www.facebook.com/messaging/send/"
    request_args = mainRequests(url, dataForm, data_fb["cookieFacebook"])
    try:
        response = await send_request_async(request_args)
        text = response.text
        if "for (;;);" in text:
            payload = text.split("for (;;);")[1].lstrip()
            res = json.loads(payload)
            if res.get("error"):
                return {"error": 1, "description": res.get("errorDescription") or "Lỗi"}
            for action in res.get("payload", {}).get("actions", []):
                if action.get("thread_fbid"):
                    return {"success": 1, "thread_id": action["thread_fbid"]}
            return {"error": 1, "description": "Không tìm thấy thread_id"}
        else:
            return {"error": 1, "description": "Cookie die / bị chặn"}
    except Exception as e:
        return {"error": 1, "description": str(e)}

async def kick_participant(data_fb, thread_id, user_ids):
    fb_id = str(data_fb["FacebookID"])
    if isinstance(user_ids, (str, int)):
        user_ids = [str(user_ids)]

    results = []
    for uid in user_ids:
        clean_uid = str(uid).replace("fbid:", "").strip()
        if not clean_uid:
            continue
        url = "https://www.facebook.com/chat/remove_participants/"
        data = formAll(data_fb, requireGraphql=False)
        data.update({"uid": clean_uid, "tid": thread_id})
        request_args = mainRequests(url, data, data_fb["cookieFacebook"])
        try:
            response = await send_request_async(request_args)
            text = response.text
            if "for (;;);" in text:
                payload = text.split("for (;;);")[1].lstrip()
                res = json.loads(payload)
                if res.get("error"):
                    results.append({"uid": clean_uid, "error": 1, "desc": res.get("errorDescription")})
                else:
                    results.append({"uid": clean_uid, "success": 1})
            else:
                results.append({"uid": clean_uid, "error": 1, "desc": "Cookie die"})
        except Exception as e:
            results.append({"uid": clean_uid, "error": 1, "desc": str(e)})
    return results

async def send_message(data_fb, thread_id, content):
    sender = SendAPI()
    try:
        result = await sender.send(
            dataFB=data_fb,
            contentSend=content,
            threadID=thread_id
        )
        return result
    except Exception as e:
        return {"error": 1, "description": str(e)}

async def create_group_with_fallback(data_fb, main_targets, secondary_targets, first_msg="Hello"):
    all_targets = main_targets + [s for s in secondary_targets if s not in main_targets]
    result = await create_group(data_fb, all_targets, first_msg)
    if not result.get("error"):
        return result
    if secondary_targets:
        result = await create_group(data_fb, main_targets, first_msg)
    return result

def load_cookies(file_path):
    if not os.path.isfile(file_path):
        print(f"❌ Không tìm thấy file {file_path}")
        return []
    cookies = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cookies.append((line_no, line))
    return cookies

def load_mess(file_path):
    if not os.path.isfile(file_path):
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

async def login_one(line_no, cookie):
    print(f"🔑 [Dòng {line_no}] Đang đăng nhập...")
    try:
        data_fb = await asyncio.wait_for(
            dataGetHome(cookie.rstrip(';').strip()),
            timeout=LOGIN_TIMEOUT
        )
        fb_id = str(data_fb.get('FacebookID'))
        print(f"   ✅ OK - FB ID: {fb_id}")
        return {"line_no": line_no, "data_fb": data_fb, "fb_id": fb_id}
    except asyncio.TimeoutError:
        print(f"   ❌ Timeout {LOGIN_TIMEOUT}s")
        return None
    except Exception as e:
        print(f"   ❌ Lỗi: {e}")
        return None

async def login_all():
    entries = load_cookies(COOKIE_FILE)
    if not entries:
        print("❌ File cookie.txt rỗng.")
        return []
    print(f"✅ Tìm thấy {len(entries)} cookie. Đăng nhập song song...\n")
    tasks = [login_one(ln, ck) for ln, ck in entries]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def test_one_account(session, main_targets, secondary_targets):
    data_fb = session["data_fb"]
    fb_id = session["fb_id"]
    print(f"\n🧪 [TEST] Account {fb_id} bắt đầu...")

    result = await create_group_with_fallback(
        data_fb, main_targets, secondary_targets, first_msg="Test"
    )

    if result.get("error"):
        print(f"   ❌ [{fb_id}] Tạo group fail: {result.get('description')}")
        return {"session": session, "ok": False, "main_results": {}}

    thread_id = result["thread_id"]
    print(f"   ✅ [{fb_id}] Tạo group OK: {thread_id}")

    main_results = {}
    for mt in main_targets:
        kr = await kick_participant(data_fb, thread_id, [mt])
        ok = any(r.get("success") for r in kr if r["uid"] == str(mt))
        main_results[mt] = ok
        print(f"      Main {mt}: {'✅ OK (đã vào group)' if ok else '❌ FAIL (không vào được)'}")

    leftover_sec = [s for s in secondary_targets if s not in main_targets]
    if leftover_sec:
        await kick_participant(data_fb, thread_id, leftover_sec)

    await kick_participant(data_fb, thread_id, [fb_id])

    all_main_ok = all(main_results.values()) if main_results else False
    return {
        "session": session,
        "ok": all_main_ok,
        "main_results": main_results,
        "thread_id": thread_id
    }

async def phase1_test(sessions, main_targets, secondary_targets):
    print("\n" + "=" * 60)
    print("PHASE 1: TEST TẤT CẢ ACCOUNT SONG SONG")
    print("=" * 60)
    tasks = [test_one_account(s, main_targets, secondary_targets) for s in sessions]
    results = await asyncio.gather(*tasks)

    print("\n" + "=" * 60)
    print("📊 KẾT QUẢ TEST")
    print("=" * 60)
    ok_sessions = []
    for r in results:
        fb_id = r["session"]["fb_id"]
        if r["ok"]:
            ok_sessions.append(r["session"])
            print(f"  ✅ Account {fb_id}: OK (tất cả main target đều vào được)")
        else:
            print(f"  ❌ Account {fb_id}: FAIL")
            for mt, ok in r["main_results"].items():
                print(f"       - Main {mt}: {'OK' if ok else 'FAIL'}")
    print("=" * 60)
    print(f"🎯 Tổng kết: {len(ok_sessions)}/{len(sessions)} account OK")
    print("=" * 60)
    return ok_sessions

async def phase2_spam_one(session, main_targets, secondary_targets, mess_content):
    data_fb = session["data_fb"]
    fb_id = session["fb_id"]
    cycle = 0

    while True:
        cycle += 1
        result = await create_group_with_fallback(
            data_fb, main_targets, secondary_targets, first_msg=f"Cycle {cycle}"
        )
        if result.get("error"):
            continue
        thread_id = result["thread_id"]

        for i in range(2):
            send_res = await send_message(data_fb, thread_id, mess_content)
            status = "OK" if not send_res.get("error") else f"FAIL ({send_res.get('description')})"
            print(f"   [{fb_id}] Cycle {cycle} - Spam {i+1}/2: {status}")
            await asyncio.sleep(0.3)

        all_targets = main_targets + [s for s in secondary_targets if s not in main_targets]
        await kick_participant(data_fb, thread_id, all_targets)
        print(f"   [{fb_id}] Cycle {cycle} - Đã kick all targets, lặp lại ngay")

async def phase2_spam(ok_sessions, main_targets, secondary_targets, mess_content):
    print("\n" + "=" * 60)
    print(f"PHASE 2: SPAM SONG SONG VỚI {len(ok_sessions)} ACCOUNT")
    print("=" * 60)
    print("(Nhấn Ctrl+C để dừng)\n")

    tasks = [
        phase2_spam_one(s, main_targets, secondary_targets, mess_content)
        for s in ok_sessions
    ]
    await asyncio.gather(*tasks)

async def main():
    sessions = await login_all()
    if not sessions:
        print("❌ Không có account nào login được.")
        return
    print(f"\n✅ {len(sessions)} account login OK.\n")

    main_input = input("Nhập MAIN TARGET UID (cách nhau dấu phẩy/khoảng trắng): ").strip()
    main_targets = [u.strip() for u in re.split(r'[,\s]+', main_input) if u.strip()]
    if not main_targets:
        print("❌ Không có main target.")
        return

    sec_input = input("Nhập SECONDARY TARGET UID (có thể bỏ trống): ").strip()
    secondary_targets = [
        u.strip() for u in re.split(r'[,\s]+', sec_input) if u.strip()
    ] if sec_input else []

    print(f"\n📋 Main targets: {main_targets}")
    print(f"📋 Secondary targets: {secondary_targets}")

    ok_sessions = await phase1_test(sessions, main_targets, secondary_targets)
    if not ok_sessions:
        print("\n❌ Không có account nào OK. Dừng.")
        return

    mess_content = load_mess(MESS_FILE)
    if mess_content is None:
        print(f"❌ Không tìm thấy {MESS_FILE}")
        return
    if not mess_content.strip():
        print(f"❌ File {MESS_FILE} rỗng.")
        return
    print(f"\n📄 Nội dung mess.txt ({len(mess_content)} ký tự): {mess_content[:80]}...")

    input(f"\n👉 Sẵn sàng spam với {len(ok_sessions)} account. Nhấn Enter để BẮT ĐẦU...")

    await phase2_spam(ok_sessions, main_targets, secondary_targets, mess_content)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Đã dừng bởi người dùng.")
