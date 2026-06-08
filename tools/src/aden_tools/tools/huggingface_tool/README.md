# HuggingFace Tool

Discover models, datasets, and spaces on HuggingFace Hub, run model inference, generate embeddings, and manage inference endpoints.

## Tools

| Tool | Description |
|------|-------------|
| `huggingface_search_models` | Search for models by query, author, or popularity |
| `huggingface_get_model` | Get details about a specific model |
| `huggingface_search_datasets` | Search for datasets by query or author |
| `huggingface_get_dataset` | Get details about a specific dataset |
| `huggingface_search_spaces` | Search for Spaces by query or author |
| `huggingface_whoami` | Get info about the authenticated HuggingFace user |
| `huggingface_run_inference` | Run inference on any model via the Inference API |
| `huggingface_run_embedding` | Generate text embeddings via the Inference API |
| `huggingface_list_inference_endpoints` | List deployed Inference Endpoints |

## Setup

Requires a HuggingFace API token:

```bash
export HUGGINGFACE_TOKEN="hf_your_token_here"
```

> Get your token at https://huggingface.co/settings/tokens

## Usage Examples

### Search for models
```python
huggingface_search_models(query="llama", sort="downloads", limit=10)
```

### Get model details
```python
huggingface_get_model(model_id="meta-llama/Llama-3-8B")
```

### Search for datasets
```python
huggingface_search_datasets(query="squad", author="rajpurkar", limit=5)
```

### Get dataset details
```python
huggingface_get_dataset(dataset_id="openai/gsm8k")
```

### Search for Spaces
```python
huggingface_search_spaces(query="stable diffusion", sort="likes", limit=10)
```

### Get authenticated user info
```python
huggingface_whoami()
```

### Run inference
```python
huggingface_run_inference(
    model_id="facebook/bart-large-cnn",
    inputs="HuggingFace is a company that builds NLP tools and hosts models...",
    parameters='{"max_new_tokens": 128}'
)
```

### Generate embeddings
```python
huggingface_run_embedding(
    model_id="sentence-transformers/all-MiniLM-L6-v2",
    inputs="The quick brown fox jumps over the lazy dog"
)
```

### List inference endpoints
```python
huggingface_list_inference_endpoints(namespace="my-org")
```

## Sort Options

| Value | Description |
|-------|-------------|
| `downloads` | Sort by download count (default for models/datasets) |
| `likes` | Sort by likes (default for spaces) |
| `lastModified` | Sort by last modified date |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "HUGGINGFACE_TOKEN not set", "help": "Get a token at https://huggingface.co/settings/tokens"}
{"error": "Unauthorized. Check your HUGGINGFACE_TOKEN."}
{"error": "Model is loading", "estimated_time": 20, "help": "The model is being loaded. Retry after the estimated time."}
{"error": "Inference request timed out. Try a smaller input or a faster model."}
{"error": "Model not found: <url>"}
```