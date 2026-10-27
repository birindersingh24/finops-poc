import { Test, TestingModule } from '@nestjs/testing';
import { BudgetsService } from './budgets.service.js';

describe('BudgetsService', () => {
  let service: BudgetsService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [BudgetsService],
    }).compile();

    service = module.get<BudgetsService>(BudgetsService);
  });

  it('should return all budgets', () => {
    expect(service.findAll()).toEqual([{ id: 1, name: 'Cloud', limit: 5000 }]);
  });
});
