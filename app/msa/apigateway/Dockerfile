# 필요프로그램 설치
FROM eclipse-temurin:17-jdk AS stage1
# 파일 복사
WORKDIR /app
COPY gradle gradle
COPY src src
COPY build.gradle .
COPY settings.gradle .
COPY gradlew .
# 빌드
RUN chmod +x gradlew
RUN ./gradlew bootJar

# 두번째 스테이지
FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY --from=stage1 /app/build/libs/*.jar app.jar

# 실행 : CMD 또는 ENTRYPOINT를 통해 컨테이너를 배열 형태의 명령어로 실행
ENTRYPOINT ["java", "-jar", "app.jar"]
