# File Parser & Summary Generator - Background Processing

FastAPI application for parsing and generating summaries from various file types (SQL, JSON, TXT, CSV) with background processing and job ID tracking.

## Main Features

- **Background processing** - files are processed asynchronously
- **Job ID tracking** - track process status with unique ID
- **Progress tracking** - monitor process stages (reading, parsing, generating_summary)
- **SQL Parser**: Extract table structures and main queries
- **JSON Parser**: Read data structures, find key fields
- **TXT Parser**: Detect file types, find important patterns (error, success, etc.)
- **CSV Parser**: Read headers, count rows, check main columns
- Automatic summary in JSON format

## Installation

```bash
pip install -r requirements.txt
```

## Running the Server

```bash
# Development mode (auto-reload)
uvicorn main:app --reload --host 0.0.0.0 --port 8001

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8001
```

API will be available at: `http://localhost:8001`

## API Endpoints

### 1. Upload File (Start Job)

```
POST /parse-file
```

**Request (multipart/form-data):**
- `file`: File (SQL, JSON, TXT, or CSV)

**Response:**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "pending",
  "message": "File 'data.csv' received. Processing..."
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
    "message": "Parsing CSV file..."
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
    "message": "Process completed!"
  },
  "result": {
    "filename": "data.csv",
    "file_type": "csv",
    "size_kb": 45.2,
    "summary": "CSV file 'data.csv' (45.2 KB). Contains 1,000 rows of data with 8 columns...",
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
pending -> reading -> parsing -> generating_summary -> completed
                                                    -> failed
```

## Usage Examples

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
  "message": "File 'data.csv' received. Processing..."
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

## Example Responses by File Type

### SQL File

```json
{
  "filename": "schema.sql",
  "file_type": "sql",
  "size_kb": 4.2,
  "summary": "SQL file 'schema.sql' (4.2 KB). Contains 15 SQL queries with 3 tables found. Database transactions present.",
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
  "summary": "JSON file 'users.json' (2.1 KB). Data structure is an array. Contains 50 records. Key fields: id, name, email, status.",
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
  "summary": "TXT file 'app.log' (8.5 KB). Detected as log_file. Contains 150 lines of text. Keywords: error(3), success(10), warning(5).",
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
  "summary": "CSV file 'sales.csv' (45.2 KB). Contains 1,000 rows of data with 8 columns. Main columns: product_id, product_name, quantity, price, total.",
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

## Notes

- Maximum file size: 5MB
- Temporary files are automatically deleted after processing completes
- All processes are performed in memory (no database required)
- CSV files read up to first 1000 rows for sample data
- Jobs are stored in memory (will be lost if server restarts)

## License Restrictions

This code is provided for **TECHNICAL TESTING AND EVALUATION PURPOSES ONLY**.

This is experimental software and is NOT intended for commercial use, production environments, or any revenue-generating activities.

By using this software, you acknowledge and agree that:
- This is experimental code provided solely for technical testing purposes
- Commercial use is strictly prohibited
- The software is provided "AS IS" without warranty of any kind
- The authors are not liable for any damages arising from its use

See the LICENSE file for complete terms and conditions.
