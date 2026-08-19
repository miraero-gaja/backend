# Deployment (planned)

Docker 외 운영 배포 artifact의 향후 위치입니다. 현재 Nginx, systemd, NCP, 데이터베이스, Redis, Kubernetes 또는 Docker Compose 설정은 구현하지 않았습니다.

G5 진입 시 public endpoint, 80/443 노출, process supervision, health check, secret injection, log redaction, timeout과 immutable image tag를 검증한 뒤 필요한 최소 설정만 추가합니다.

