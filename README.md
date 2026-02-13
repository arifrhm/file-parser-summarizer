# File Parser & Summary Generator - Background Processing

FastAPI aplikasi untuk parsing dan generate ringkasan dari berbagai jenis file (SQL, JSON, TXT, CSV) dengan background processing dan job ID tracking.

## Fitur Utama

- Background processing - file diproses secara asynchronous
- Job ID tracking - lacak status proses dengan unique ID
- Progress tracking - pantau tahapan proses (reading, parsing, generating_summary)
- **SQL Parser**: Ekstrak struktur tabel dan query utama
- **JSON Parser**: Baca struktur data, cari field utama
- **TXT Parser**: Deteksi tipe file, cari pola penting (error, success, dll)
- **CSV Parser**: Baca header, hitung baris, cek kolom utama
- Ringkasan otomatis dalam format JSON

## Instalasi

```bash
pip install -r requirements.txt
```

## Menjalankan Server

```bash
# Development mode (auto-reload)
uvicorn main:app --reload --host 0.0.0.0 --port 8001

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8001
```

API akan tersedia di: `http://localhost:8001`

## API Endpoints

### 1. Upload File (Start Job)

```
POST /parse-file
```

**Request (multipart/form-data):**
- `file`: File (SQL, JSON, TXT, atau CSV)

**Response:**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "pending",
  "message": "File 'data.csv' diterima. Sedang diproses."
}
```

### 2. Check Job Status

```
GET /jobs/{job_id}
```

**Response (Processing):**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "processing",
  "file_type": "csv",
  "filename": "data.csv",
  "file_size_kb": 45.2,
  "created_at": "2025-01-15T10:30:00",
  "started_at": "2025-01-15T10:30:01",
  "completed_at": null,
  "progress": {
    "stage": "parsing",
    "message": "MemParsing file CSV..."
  }
}
```

**Response (Completed):**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "completed",
  "file_type": "csv",
  "filename": "data.csv",
  "file_size_kb": 45.2,
  "created_at": "2025-01-15T10:30:00",
  "started_at": "2025-01-15T10:30:01",
  "completed_at": "2025-01-15T10:30:05",
  "progress": {
    "stage": "completed",
    "message": "Proses selesai!"
  },
  "result": {
    "filename": "data.csv",
    "file_type": "csv",
    "size_kb": 45.2,
    "summary": "File CSV 'data.csv' (45.2 KB). Berisi 1,000 baris data dengan 8 kolom...",
    "key_info": {
      "rows": 1000,
      "columns": 8,
      "main_columns": ["product_id", "product_name", "quantity", "price", "total"]
    }
  }
}
```

### 3. List All Jobs

```
GET /jobs
```

### 4. Delete Job

```
DELETE /jobs/{job_id}
```

### 5. Health Check

```
GET /health
```

## Progress Stages

```
pending → reading → parsing → generating_summary → completed
                                                    ↘ failed
```

## Contoh Penggunaan

### 1. Upload File & Get Job ID

```bash
curl -X POST "http://localhost:8001/parse-file" \
  -F "file=@data.csv"
```

**Response:**
```json
{
  "job_id": "abc-123-def-456",
  "status": "pending",
  "message": "File 'data.csv' diterima. Sedang diproses."
}
```

### 2. Poll Job Status

```bash
curl "http://localhost:8001/jobs/abc-123-def-456"
```

### 3. Python Polling Example

```python
import requests
import time

# Upload file
response = requests.post(
    "http://localhost:8001/parse-file",
    files={"file": open("data.csv", "rb")}
)
job_id = response.json()["job_id"]

# Poll status
while True:
    status = requests.get(f"http://localhost:8001/jobs/{job_id}").json()
    print(f"Status: {status['status']} - Stage: {status['progress']['stage']}")

    if status["status"] in ["completed", "failed"]:
        if status["status"] == "completed":
            result = status["result"]
            print(f"Summary: {result['summary']}")
        break

    time.sleep(1)
```

### 4. JavaScript Polling Example

```javascript
// Upload file
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const uploadResponse = await fetch('http://localhost:8001/parse-file', {
  method: 'POST',
  body: formData
});
const { job_id } = await uploadResponse.json();

// Poll status
const pollStatus = async () => {
  const response = await fetch(`http://localhost:8001/jobs/${job_id}`);
  const data = await response.json();

  console.log(`Status: ${data.status} - Stage: ${data.progress.stage}`);

  if (data.status === 'completed') {
    console.log('Summary:', data.result.summary);
  } else if (data.status !== 'failed') {
    setTimeout(pollStatus, 1000);
  }
};

pollStatus();
```

## Contoh Response Per Tipe File

### SQL File

```json
{
  "filename": "schema.sql",
  "file_type": "sql",
  "size_kb": 4.2,
  "summary": "File SQL 'schema.sql' (4.2 KB). Berisi 15 query SQL dengan 3 tabel yang ditemukan. Terdapat transaksi database.",
  "key_info": {
    "tables_found": ["users", "products", "orders"],
    "tables_count": 3,
    "total_queries": 15,
    "query_types": {
      "CREATE": 3,
      "INSERT": 10,
      "SELECT": 2
    },
    "has_transaction": true
  }
}
```

### JSON File

```json
{
  "filename": "users.json",
  "file_type": "json",
  "size_kb": 2.1,
  "summary": "File JSON 'users.json' (2.1 KB). Struktur data berupa array. Berisi 50 record. Field utama: id, name, email, status.",
  "key_info": {
    "structure_type": "array",
    "record_count": 50,
    "key_fields": ["id", "name", "email", "status", "created_at"]
  }
}
```

### TXT File

```json
{
  "filename": "app.log",
  "file_type": "txt",
  "size_kb": 8.5,
  "summary": "File TXT 'app.log' (8.5 KB). Terdeteksi sebagai log_file. Berisi 150 baris teks. Kata kunci: error(3), success(10), warning(5).",
  "key_info": {
    "detected_type": "log_file",
    "total_lines": 150,
    "non_empty_lines": 145,
    "keyword_counts": {
      "error": 3,
      "success": 10,
      "warning": 5
    },
    "important_lines": [
      {
        "line_number": 42,
        "type": "error",
        "content": "ERROR: Connection timeout to database server"
      }
    ]
  }
}
```

### CSV File

```json
{
  "filename": "sales.csv",
  "file_type": "csv",
  "size_kb": 45.2,
  "summary": "File CSV 'sales.csv' (45.2 KB). Berisi 1,000 baris data dengan 8 kolom. Kolom utama: product_id, product_name, quantity, price, total.",
  "key_info": {
    "rows": 1000,
    "columns": 8,
    "main_columns": ["product_id", "product_name", "quantity", "price", "total"],
    "sample_first_rows": [
      {"product_id": 1, "product_name": "Laptop", "quantity": 2, "price": 1500.0}
    ]
  }
}
```

## Catatan

- Maksimal ukuran file: 5MB
- File sementara otomatis dihapus setelah proses selesai
- Semua proses dilakukan di memori (tidak perlu database)
- CSV dibaca sampai 1000 baris pertama untuk sample data
- Job tersimpan di memory (akan hilang jika server restart)
