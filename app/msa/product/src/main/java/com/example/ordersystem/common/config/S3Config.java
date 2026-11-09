package com.example.ordersystem.common.config;

import com.amazonaws.auth.DefaultAWSCredentialsProviderChain;
import com.amazonaws.services.s3.AmazonS3;
import com.amazonaws.services.s3.AmazonS3ClientBuilder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class S3Config {

    // 기존 서울 리전 설정 사용
    @Value("${cloud.aws.region.static:ap-northeast-2}")
    private String region;

    @Bean
    public AmazonS3 amazonS3() {
        return AmazonS3ClientBuilder.standard()
                .withRegion(region)
                // EKS에서는 ServiceAccount 토큰을 사용해 임시 자격증명 획득
                .withCredentials(DefaultAWSCredentialsProviderChain.getInstance())
                .build();
    }
}
