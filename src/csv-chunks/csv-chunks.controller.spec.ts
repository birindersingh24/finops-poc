import { Test, TestingModule } from '@nestjs/testing';
import { CostsController } from './csv-chunks.controller.js';
import { CostsService } from './csv-chunks.service.js';

describe('CostsController', () => {
  let controller: CostsController;
  const costsService = { findAll: vi.fn() };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      controllers: [CostsController],
      providers: [{ provide: CostsService, useValue: costsService }],
    }).compile();

    controller = module.get<CostsController>(CostsController);
  });

  it('should delegate findAll to the service', () => {
    costsService.findAll.mockReturnValue([]);

    expect(controller.findAll()).toEqual([]);
    expect(costsService.findAll).toHaveBeenCalled();
  });
});
