SERVICES := $(filter frontend backend,$(MAKECMDGOALS))

.PHONY: up frontend backend

up:
	docker compose up --build -d $(SERVICES)

frontend backend:
	@:
