import { Test, TestingModule } from '@nestjs/testing';
import { INestApplication } from '@nestjs/common';
import request from 'supertest';
import { App } from 'supertest/types.js';
import { AppModule } from './../src/app.module.js';

describe('BudgetsController (e2e)', () => {
  let app: INestApplication<App>;

  beforeEach(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  it('/budgets (GET)', () => {
    return request(app.getHttpServer())
      .get('/budgets')
      .expect(200)
      .expect([{ id: 1, name: 'Cloud', limit: 5000 }]);
  });

  afterEach(async () => {
    await app.close();
  });
});
