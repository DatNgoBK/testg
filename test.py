import asyncio
import httpx
import json

# --- CÁC THÔNG SỐ BẠN CẦN THAY ĐỔI ---

# 1. Địa chỉ cơ sở của API của bạn (ví dụ: http://localhost:8000)
#    Thay đổi cho đúng với môi trường của bạn.
BASE_URL = "http://127.0.0.1:8000"

# 2. API Key để xác thực (nếu API của bạn yêu cầu)
#    Dựa vào code gọi API bạn cung cấp, có vẻ API cần "X-API-Key".
API_KEY = "YOUR_SECRET_API_KEY" 

# 3. Mã Epic bạn muốn kiểm tra (ví dụ: "PROJ-123")
EPIC_KEY_TO_TEST = "PROJECT-456"

# --------------------------------------------

async def call_epic_overview_api():
    """
    Hàm bất đồng bộ để gọi và kiểm tra API get_jira_epic_overview.
    """
    # Xây dựng URL đầy đủ dựa trên endpoint: /jira/epics/{epic_key}/overview
    url = f"{BASE_URL}/jira/epics/{EPIC_KEY_TO_TEST}/overview"
    
    # Chuẩn bị headers cho request, giống như trong code gọi API của bạn
    headers = {
        "accept": "application/json",
        "X-API-Key": API_KEY 
    }

    print(f"🚀 Đang gửi yêu cầu GET tới: {url}")
    print(f"🔑 Với Epic Key: {EPIC_KEY_TO_TEST}")

    # Sử dụng httpx.AsyncClient để thực hiện request bất đồng bộ
    try:
        # async with đảm bảo client được đóng đúng cách sau khi dùng xong
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Gửi yêu cầu GET
            response = await client.get(url, headers=headers)

            # raise_for_status() sẽ tự động báo lỗi nếu status code là 4xx hoặc 5xx
            response.raise_for_status()

            # Nếu thành công (status code là 200-299)
            print(f"\n✅ Yêu cầu thành công! Status Code: {response.status_code}")
            
            # Lấy dữ liệu JSON từ response và in ra một cách đẹp mắt
            data = response.json()
            print("📝 Dữ liệu nhận được:")
            # json.dumps với indent=4 giúp format JSON cho dễ đọc
            print(json.dumps(data, indent=4, ensure_ascii=False))

    except httpx.HTTPStatusError as e:
        # Xử lý các lỗi HTTP trả về từ server (ví dụ: 404 Not Found, 500 Internal Server Error)
        print(f"\n❌ Lỗi HTTP! Status Code: {e.response.status_code}")
        print(f"   Nội dung lỗi từ server: {e.response.text}")
    except httpx.RequestError as e:
        # Xử lý các lỗi kết nối (ví dụ: không thể kết nối tới server, sai địa chỉ)
        print(f"\n❌ Lỗi kết nối! Không thể kết nối tới API tại '{e.request.url}'.")
        print(f"   Vui lòng kiểm tra lại địa chỉ BASE_URL và đảm bảo API server đang chạy.")
    except Exception as e:
        # Xử lý các lỗi khác không mong muốn
        print(f"\n❌ Đã xảy ra lỗi không xác định: {e}")

# Đây là điểm khởi chạy chính của script
if __name__ == "__main__":
    # Kiểm tra xem người dùng đã thay đổi các giá trị placeholder chưa
    if "YOUR_SECRET_API_KEY" in API_KEY or "127.0.0.1:8000" == BASE_URL:
        print("⚠️  Cảnh báo: Vui lòng cập nhật các giá trị BASE_URL, API_KEY, và EPIC_KEY_TO_TEST trong file code trước khi chạy!")
        print("-" * 50)

    # Sử dụng asyncio.run() để thực thi hàm bất đồng bộ call_epic_overview_api
    asyncio.run(call_epic_overview_api())
