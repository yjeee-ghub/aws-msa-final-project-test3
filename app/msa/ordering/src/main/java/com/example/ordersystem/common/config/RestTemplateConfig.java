package com.example.ordersystem.common.config;


import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    @Bean
//    Kubernetes Service DNS를 사용해서 내부 서비스 호출
    public RestTemplate restTemplate(){
        return new RestTemplate();
    }
}
