up:
	docker compose pull --quiet
	docker compose build
	docker compose up --exit-code-from app app
