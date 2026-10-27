import { Test, TestingModule } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import request from 'supertest';
import { App } from 'supertest/types.js';
import { AppModule } from './../src/app.module.js';

describe('CostsController (e2e)', () => {
  let app: INestApplication<App>;

  beforeEach(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  it('/costs (GET)', () => {
    return request(app.getHttpServer())
      .get('/costs')
      .expect(200)
      .expect([{ id: 1, service: 'EC2', amount: 1200 }]);
  });

  afterEach(async () => {
    await app.close();
  });
});
