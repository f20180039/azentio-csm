FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B package -DskipTests

FROM eclipse-temurin:17-jre
RUN useradd --system --uid 10001 app && mkdir -p /data/uploads && chown app /data/uploads
WORKDIR /app
COPY --from=build /src/target/case-intel-api-*.jar app.jar
USER app
ENV STORAGE_DIR=/data/uploads
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
